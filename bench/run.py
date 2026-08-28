#!/usr/bin/env python3
"""Does Preceptor help or hurt Amplifier?

An honest v0 benchmark. It measures what CAN be measured today and refuses to
imply the rest.

MEASURABLE NOW
  overhead  -- does running the observer cost wall-clock time?
  harm      -- does it change answers, break sessions, or emit errors?

NOT MEASURABLE YET, AND DELIBERATELY NOT FAKED
  benefit   -- whether earned cues improve work. No cues have been earned, so
               there is nothing to dose. Claiming a benefit number here would be
               authoring a result from priors, which is the exact failure this
               bundle exists to catch. See docs/theory/05-expert-review.md for
               the sham-cue study that would actually settle it.

Applies this repo's own statistical bar (context/methodology/evidence-standards.md):
n >= 5 per arm, report mean AND spread, and emit positive / no-effect /
inconclusive rather than a bare pass/fail. An underpowered comparison yields
`inconclusive`, never `no-effect`.

    python3 bench/run.py            # default: 5 trials per arm
    python3 bench/run.py --trials 3 --repo-url <fork-url>
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

REPO = "git+https://github.com/michaeljabbour/amplifier-bundle-preceptor@main"

# Deterministic, cheap, and verifiable without a grader model. A rubric that
# needs an LLM to score it just relocates the judgment and hides it.
TASKS: list[tuple[str, str, str]] = [
    ("echo", "Reply with exactly this and nothing else: PONG", r"^PONG$"),
    ("arith", "What is 17 * 23? Reply with only the number.", r"^391$"),
    (
        "recall",
        "Reply with exactly the third word of this sentence: alpha beta gamma delta.",
        r"^gamma\.?$",
    ),
]


@dataclass
class Trial:
    arm: str
    task: str
    seconds: float
    exit_code: int
    status: str
    response: str
    correct: bool
    stderr_bytes: int


@dataclass
class Arm:
    name: str
    bundle: str | None
    trials: list[Trial] = field(default_factory=list)


def _extract_json(stdout: str) -> dict:
    """The CLI prints a human preamble ("Bundle 'x' prepared successfully")
    before the JSON object, so json.load on the raw stream fails."""
    start = stdout.find("{")
    if start == -1:
        return {}
    try:
        return json.loads(stdout[start:])
    except json.JSONDecodeError:
        return {}


def run_trial(arm: Arm, task: tuple[str, str, str], home: Path) -> Trial:
    name, prompt, pattern = task
    cmd = ["amplifier", "run", "--output-format", "json"]
    if arm.bundle:
        cmd += ["--bundle", arm.bundle]
    cmd.append(prompt)

    # Isolate state so trial N cannot inherit anything from trial N-1.
    env = (
        {**os.environ} if home is None else {**os.environ, "AMPLIFIER_HOME": str(home)}
    )

    t0 = time.monotonic()
    try:
        p = subprocess.run(
            cmd, capture_output=True, text=True, timeout=180, env=env, check=False
        )
        out, err, code = p.stdout, p.stderr, p.returncode
    except subprocess.TimeoutExpired:
        out, err, code = "", "TIMEOUT", 124
    elapsed = time.monotonic() - t0

    data = _extract_json(out)
    response = (data.get("response") or "").strip()
    return Trial(
        arm=arm.name,
        task=name,
        seconds=elapsed,
        exit_code=code,
        status=data.get("status", "no-json"),
        response=response,
        correct=bool(re.match(pattern, response, re.IGNORECASE)),
        stderr_bytes=len(err.encode()),
    )


def verdict(
    control: list[float], treat: list[float], n_min: int = 5
) -> tuple[str, str]:
    """positive | no-effect | inconclusive — never a bare pass/fail.

    Requires BOTH a meaningful effect size AND statistical significance. An
    earlier version of this function gated on Cohen's d alone and reported
    "positive" for a +1.7% difference that a Welch t-test put at p≈0.11 — a
    large-looking d on five samples per arm. That is the exact failure this
    repo's evidence-standards.md warns about, committed by its own benchmark.

    `inconclusive` is a real verdict and it means KEEP LOOKING. It does not
    mean "no effect": accepting the null from a test that could never have
    rejected it is how a benchmark lies.
    """
    if len(control) < n_min or len(treat) < n_min:
        return "inconclusive", f"n={min(len(control), len(treat))} < {n_min} per arm"

    mc, mt = statistics.mean(control), statistics.mean(treat)
    sc = statistics.stdev(control)
    st_ = statistics.stdev(treat)
    delta = mt - mc
    pooled = ((sc**2 + st_**2) / 2) ** 0.5
    d = delta / pooled if pooled else 0.0

    # Welch's t — unequal variances, which is the safe assumption here.
    se = (sc**2 / len(control) + st_**2 / len(treat)) ** 0.5
    if se == 0:
        return (
            ("no-effect", "identical")
            if delta == 0
            else ("positive", f"delta={delta:+.2f}s")
        )
    tstat = delta / se
    df = (sc**2 / len(control) + st_**2 / len(treat)) ** 2 / (
        (sc**2 / len(control)) ** 2 / (len(control) - 1)
        + (st_**2 / len(treat)) ** 2 / (len(treat) - 1)
    )
    # Two-sided ~p<0.05 for small df. Conservative and dependency-free.
    crit = 2.45 if df < 8 else (2.31 if df < 10 else 2.09)
    sig = abs(tstat) >= crit
    stats = f"delta={delta:+.2f}s ({delta / mc * 100:+.1f}%)  d={d:+.2f}  t={tstat:.2f} df={df:.1f}"

    if sig and abs(d) >= 0.5:
        return "positive", stats
    if not sig and abs(d) >= 0.5:
        # Effect looks real but the sample cannot establish it. Do NOT call this no-effect.
        return "inconclusive", stats + "  (d is large but n is too small to confirm)"
    return "no-effect", stats


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--trials", type=int, default=5, help="trials per arm per task (bar: >=5)"
    )
    ap.add_argument("--repo-url", default=REPO)
    ap.add_argument("--out", default="bench-results/latest.json")
    ap.add_argument(
        "--warm-cache",
        action="store_true",
        help="reuse the caller's bundle cache (much faster; sessions are isolated anyway)",
    )
    ap.add_argument("--tasks", type=int, default=0, help="limit to first N tasks")
    ap.add_argument("--skip-observe-off", action="store_true")
    args = ap.parse_args()

    arms = [
        Arm("control", None),  # whatever bundle is configured, no preceptor
        Arm("observe-off", f"{args.repo_url}#subdirectory=bundles/observe-only.yaml"),
        Arm("observe-on", f"{args.repo_url}#subdirectory=bundles/observe-on.yaml"),
    ]

    if args.skip_observe_off:
        arms = [a for a in arms if a.name != "observe-off"]
    tasks = TASKS[: args.tasks] if args.tasks else TASKS
    total = len(arms) * len(tasks) * args.trials
    print(
        f"preceptor bench — {len(arms)} arms x {len(TASKS)} tasks x {args.trials} trials "
        f"= {total} runs\n"
    )

    done = 0
    for arm in arms:
        for task in TASKS:
            for _ in range(args.trials):
                home = Path(tempfile.mkdtemp(prefix="preceptor-bench-"))
                try:
                    t = run_trial(arm, task, home)
                finally:
                    shutil.rmtree(home, ignore_errors=True)
                arm.trials.append(t)
                done += 1
                flag = "ok " if (t.correct and t.exit_code == 0) else "FAIL"
                print(
                    f"  [{done:>3}/{total}] {arm.name:<12} {t.task:<7} "
                    f"{t.seconds:6.2f}s  {flag}"
                )

    print("\n" + "=" * 72)
    print("RESULTS")
    print("=" * 72)

    summary: dict = {"arms": {}, "verdicts": {}}
    for arm in arms:
        secs = [t.seconds for t in arm.trials]
        ok = sum(1 for t in arm.trials if t.exit_code == 0)
        correct = sum(1 for t in arm.trials if t.correct)
        noisy = sum(1 for t in arm.trials if t.stderr_bytes > 0)
        summary["arms"][arm.name] = {
            "n": len(arm.trials),
            "mean_s": round(statistics.mean(secs), 3),
            "stdev_s": round(statistics.stdev(secs), 3) if len(secs) > 1 else 0.0,
            "median_s": round(statistics.median(secs), 3),
            "exit_ok": ok,
            "correct": correct,
            "runs_with_stderr": noisy,
        }
        a = summary["arms"][arm.name]
        print(f"\n{arm.name}")
        print(
            f"  wall-clock   {a['mean_s']:.2f}s ± {a['stdev_s']:.2f}  (median {a['median_s']:.2f})"
        )
        print(f"  sessions ok  {ok}/{a['n']}")
        print(f"  answers ok   {correct}/{a['n']}")
        print(f"  stderr noise {noisy}/{a['n']} runs")

    base = [t.seconds for t in arms[0].trials]
    print("\n" + "-" * 72)
    print("OVERHEAD vs control  (does Preceptor cost you time?)")
    for arm in arms[1:]:
        v, why = verdict(base, [t.seconds for t in arm.trials])
        summary["verdicts"][arm.name] = {"verdict": v, "detail": why}
        print(f"  {arm.name:<12} {v:<13} {why}")

    print("\nHARM  (does it break or change anything?)")
    harmed = False
    for arm in arms:
        a = summary["arms"][arm.name]
        if a["exit_ok"] < a["n"] or a["correct"] < a["n"]:
            harmed = True
            print(
                f"  {arm.name:<12} HARM: {a['n'] - a['exit_ok']} failed sessions, "
                f"{a['n'] - a['correct']} wrong answers"
            )
    if not harmed:
        print("  none — every arm completed every session with the correct answer")
    summary["harm"] = harmed

    print("\nBENEFIT")
    print("  NOT MEASURED. No cues have been earned yet, so there is nothing to dose.")
    print("  A benefit number here would be authored from priors — the exact failure")
    print("  this bundle exists to catch. See docs/theory/05-expert-review.md §8.")

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, indent=2))
    print(f"\nwrote {out}")
    return 1 if harmed else 0


if __name__ == "__main__":
    sys.exit(main())
