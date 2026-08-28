#!/usr/bin/env python3
"""Roll up `amplifier-evaluation` trial results into per-arm statistics.

The evaluation harness writes one `state.json` per trial and a `summary.json`
that is counts only -- no CSV, no JSONL, no cross-trial rollup, and no arm
comparison. This closes that gap.

Every metric here is judge-free by construction. Nothing in this file reads a
trajectory and forms an opinion about it: arXiv:2608.22960 showed full-trace
LLM judges score semantic relevance rather than causal contribution, so a
judge-based trajectory metric measures the wrong thing from day one.

    python3 bench/aggregate.py bench-results/ablation-001 --control baseline

Expected layout (produced by `amplifier-evaluation run`):

    <run>/trials/<agent>__<task>__trial-<n>/
        state.json                          agent id, elapsed, grader score
        extraction/**/transcript.jsonl      -> correction turns
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from correction_turns import analyze
from verdict import compare, required_n


@dataclass
class TrialRow:
    arm: str
    task: str
    trial: int
    ok: bool
    elapsed_s: float
    score: float | None
    corrections: int | None
    redirects: int | None


@dataclass
class ArmStats:
    name: str
    rows: list[TrialRow] = field(default_factory=list)

    def series(self, attr: str) -> list[float]:
        return [
            float(getattr(r, attr)) for r in self.rows if getattr(r, attr) is not None
        ]


def _load_trial(d: Path) -> TrialRow | None:
    sj = d / "state.json"
    if not sj.is_file():
        return None
    try:
        s = json.loads(sj.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None

    grader = s.get("grader") or {}
    score = grader.get("overall_score")

    # Correction turns come from the extracted agent transcript. Absent on a
    # trial that failed before extraction -- recorded as None, never as 0,
    # because 0 is a real and very good value and must not be faked.
    corr = redir = None
    tx = sorted(d.glob("extraction/**/transcript.jsonl"))
    if tx:
        reps = [analyze(t) for t in tx]
        corr = sum(r.correction_turns for r in reps)
        redir = sum(r.counts["redirect"] for r in reps)

    return TrialRow(
        arm=s.get("agent_id") or "?",
        task=s.get("task_id") or "?",
        trial=int(s.get("trial_number") or 0),
        ok=s.get("state") == "completed",
        elapsed_s=float(s.get("elapsed_s") or 0.0),
        score=float(score) if isinstance(score, (int, float)) else None,
        corrections=corr,
        redirects=redir,
    )


METRICS = [
    # attr, label, direction ("lower" = lower is better)
    ("corrections", "corrections/session", "lower"),
    ("redirects", "redirects/session", "lower"),
    ("score", "grader score", "higher"),
    ("elapsed_s", "wall clock (s)", "lower"),
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("run_dir", help="an amplifier-evaluation run output dir")
    ap.add_argument(
        "--control", default="baseline", help="arm to compare others against"
    )
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    root = Path(args.run_dir)
    if not root.is_dir():
        print(f"not a directory: {root}", file=sys.stderr)
        return 2
    trials_dir = root / "trials" if (root / "trials").is_dir() else root
    rows = [
        r
        for d in sorted(trials_dir.iterdir())
        if d.is_dir()
        for r in [_load_trial(d)]
        if r
    ]

    if not rows:
        print(f"no trials found under {trials_dir}", file=sys.stderr)
        return 2

    arms: dict[str, ArmStats] = defaultdict(lambda: ArmStats(""))
    for r in rows:
        arms.setdefault(r.arm, ArmStats(r.arm)).rows.append(r)
    for k, v in arms.items():
        v.name = k

    print(f"{len(rows)} trials across {len(arms)} arms\n")
    print(
        f"{'arm':<16} {'n':>4} {'ok':>5} {'corr':>8} {'redir':>8} {'score':>8} {'secs':>9}"
    )
    print("-" * 64)
    for name in sorted(arms):
        a = arms[name]
        n = len(a.rows)
        ok = sum(1 for r in a.rows if r.ok)

        def m(attr: str, a: ArmStats = a) -> str:
            s = a.series(attr)
            return f"{statistics.mean(s):.2f}" if s else "—"

        print(
            f"{name:<16} {n:>4} {ok:>4}/{n} {m('corrections'):>8} "
            f"{m('redirects'):>8} {m('score'):>8} {m('elapsed_s'):>9}"
        )

    ctrl = arms.get(args.control)
    if not ctrl:
        print(
            f"\ncontrol arm '{args.control}' not present; skipping comparison",
            file=sys.stderr,
        )
        return 0

    out: dict = {"control": args.control, "arms": {}, "comparisons": {}}
    print(f"\n{'=' * 64}\nvs. control '{args.control}'")

    for name in sorted(k for k in arms if k != args.control):
        print(f"\n  {name}")
        out["comparisons"][name] = {}
        for attr, label, direction in METRICS:
            c, t = ctrl.series(attr), arms[name].series(attr)
            if not c or not t:
                print(f"    {label:<22} — (no data)")
                continue
            r = compare(c, t)
            better = ""
            if r.verdict == "positive":
                improved = (r.delta < 0) if direction == "lower" else (r.delta > 0)
                better = "  BETTER" if improved else "  WORSE"
            print(f"    {label:<22} {r.verdict:<13} {r.detail}{better}")
            out["comparisons"][name][attr] = {
                "verdict": r.verdict,
                "detail": r.detail,
                "delta": r.delta,
                "cohens_d": r.cohens_d,
                "n_control": r.n_control,
                "n_treat": r.n_treat,
            }

    # Power, stated up front rather than discovered afterwards.
    base = ctrl.series("corrections") or ctrl.series("elapsed_s")
    if base:
        n_now = len(base)
        print(
            f"\n{'-' * 64}\npower: n={n_now} per arm. "
            f"Need ~{required_n(base, 0.8)} for a large effect (d=0.8), "
            f"~{required_n(base, 0.5)} for medium (d=0.5)."
        )
        if n_now < required_n(base, 0.8):
            print("      Underpowered for anything but a very large effect.")
            print("      'inconclusive' below means KEEP LOOKING, not 'no effect'.")

    if args.json:
        (root / "aggregate.json").write_text(json.dumps(out, indent=2))
        print(f"\nwrote {root / 'aggregate.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
