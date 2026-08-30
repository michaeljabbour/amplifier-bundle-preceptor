#!/usr/bin/env python3
"""Ablate the always-on context files and measure what breaks.

THE RULE THIS ENFORCES
----------------------
`context/cue-awareness.md` says, of this very bundle:

    Never propose removing a cue, a context file, or an instruction on judgment
    alone.

So a context reduction cannot be justified by "it reads fine to me." It needs
evidence that the reduced version still enables what the full version enabled.
This is that evidence.

HOW
---
Each probe is a question the context exists to let the agent answer, plus a regex
the answer must match. The exit code IS the grade -- no LLM judge anywhere, because
arXiv:2608.22960 showed full-trace judges score semantic relevance rather than
causal contribution.

Two arms, one container, same session machinery:

    full      the shipped context files
    reduced   a candidate with fewer tokens

Variants are written directly into the bundle cache inside the container, so both
arms differ ONLY in the bytes of the context files. No git round-trip, no
composition difference, no second variable.

ADMISSIBILITY
-------------
A probe only counts if the FULL context passes it. A probe the full context
already fails measures a gap in the context, not a loss from the reduction --
and counting it would let a reduction "preserve" a capability that never existed.

    python3 bench/probe_context.py --reps 3
"""

from __future__ import annotations

import argparse
import base64
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from climb import Measurement, Mutation, decide

HERE = Path(__file__).parent
PROBES = json.loads((HERE / "probes" / "context-probes.json").read_text())["probes"]
BUNDLE = (
    "git+https://github.com/michaeljabbour/amplifier-bundle-preceptor@main"
    "#subdirectory=bundles/observe-on.yaml"
)


def sh(container: str, script: str, timeout: int = 900) -> str:
    """Run a bash script inside the DTU and return stdout."""
    b64 = base64.b64encode(script.encode()).decode()
    p = subprocess.run(
        [
            "amplifier-digital-twin",
            "exec",
            "--timeout",
            "none",
            container,
            "--",
            "bash",
            "-lc",
            f"echo {b64} | base64 -d > /tmp/s.sh && bash /tmp/s.sh",
        ],
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    i = p.stdout.find("{")
    if i == -1:
        return p.stdout
    try:
        return json.loads(p.stdout[i:]).get("stdout") or ""
    except json.JSONDecodeError:
        return p.stdout


def install_variant(container: str, variant: dict[str, str]) -> None:
    """Overwrite the cached context files with a variant. The ONLY thing that differs."""
    lines = [
        "set -e",
        "C=$(ls -d /root/.amplifier/cache/amplifier-bundle-preceptor-* | head -1)",
    ]
    for name, body in variant.items():
        b64 = base64.b64encode(body.encode()).decode()
        lines.append(f'echo {b64} | base64 -d > "$C/context/{name}"')
    lines.append('echo "installed: $(wc -c "$C"/context/*.md | tail -1)"')
    print("   ", sh(container, "\n".join(lines)).strip()[:120])


def ask(container: str, question: str) -> str:
    script = (
        "cd /root && PRECEPTOR_ENABLED=1 amplifier run --bundle "
        f"'{BUNDLE}' --output-format json {json.dumps(question)} 2>/dev/null"
    )
    out = sh(container, script)
    i = out.find("{")
    if i == -1:
        return out.strip()
    try:
        return (json.loads(out[i:]).get("response") or "").strip()
    except json.JSONDecodeError:
        return out.strip()


def run_arm(container: str, label: str, variant: dict[str, str], reps: int) -> dict:
    print(f"\n  arm: {label}")
    install_variant(container, variant)
    chars = sum(len(v) for v in variant.values())
    results: dict[str, list[bool]] = {}
    for probe in PROBES:
        hits = []
        for _ in range(reps):
            a = ask(container, probe["question"])
            ok = bool(re.search(probe["expect"], a))
            if ok and probe.get("must_not"):
                ok = not re.search(probe["must_not"], a)
            hits.append(ok)
        results[probe["id"]] = hits
        n = sum(hits)
        print(f"    {probe['id']:<16} {n}/{reps} {'ok' if n == reps else 'MISS'}")
    return {"chars": chars, "tokens_est": chars // 4, "results": results}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--container", default="pphase")
    ap.add_argument("--reps", type=int, default=3)
    ap.add_argument("--out", default="bench-results/context-ablation.json")
    args = ap.parse_args()

    full = {
        "awareness.md": (HERE.parent / "context" / "awareness.md").read_text(),
        "cue-awareness.md": (HERE.parent / "context" / "cue-awareness.md").read_text(),
    }
    reduced_path = HERE / "probes" / "reduced"
    if not reduced_path.is_dir():
        print(f"no reduced variant at {reduced_path}", file=sys.stderr)
        return 2
    reduced = {p.name: p.read_text() for p in sorted(reduced_path.glob("*.md"))}

    print("=" * 70)
    print("CONTEXT ABLATION -- does the reduction preserve what the context enables?")
    print("=" * 70)
    print(
        f"  full     {sum(len(v) for v in full.values()):>5}c  "
        f"~{sum(len(v) for v in full.values()) // 4} tok"
    )
    print(
        f"  reduced  {sum(len(v) for v in reduced.values()):>5}c  "
        f"~{sum(len(v) for v in reduced.values()) // 4} tok"
    )

    # The attribution arm. Empty context files = the bundle composes, mounts, and
    # injects nothing. Anything still answered here was never being carried by
    # these tokens.
    a_none = run_arm(args.container, "no-context", dict.fromkeys(full, ""), args.reps)
    a_full = run_arm(args.container, "full", full, args.reps)
    a_red = run_arm(args.container, "reduced", reduced, args.reps)

    print("\n" + "=" * 70)
    print("VERDICT")
    print("=" * 70)
    passes_full = [p for p in PROBES if all(a_full["results"][p["id"]])]
    # Over-determined: the no-context arm answers it too, so these tokens are not
    # what produce the behavior. Verified for `removal-burden`: 3/3 with no
    # Preceptor context present at all.
    over = [p for p in passes_full if any(a_none["results"][p["id"]])]
    admissible = [p for p in passes_full if p not in over]
    inadmissible = [p["id"] for p in PROBES if p not in passes_full]
    if inadmissible:
        print(
            f"  EXCLUDED (full context already fails these): {', '.join(inadmissible)}"
        )
        print("  A probe the full context fails measures a gap, not a loss.")
    if over:
        print(
            f"  OVER-DETERMINED (no-context arm passes): "
            f"{', '.join(p['id'] for p in over)}"
        )
        print("    The model answers these WITHOUT the context. Those tokens are not")
        print("    carrying the behavior -- preserving them proves nothing, and they")
        print("    are the prime removal candidates.")

    saved = a_full["chars"] - a_red["chars"]

    # THE ACCEPT RULE: pooled non-inferiority via climb.decide() -- the same
    # asymmetric rule the calibration loop uses for a REMOVE move.
    #
    # The previous rule required EVERY rep of EVERY admissible probe to pass. That
    # is unsound and provably so without reference to any outcome: at a per-rep
    # pass rate of 0.95 with 4 probes x 5 reps, a PERFECT reduction survives with
    # probability 0.95^20 = 0.358 -- rejected 64% of the time. Two runs confirmed
    # it: awareness.md was byte-identical across both, yet delete-records scored
    # 5/5 then 4/5 and stop-recording 3/5 then 2/5 in the untouched full arm.
    # Same bytes, different verdict. That gate measured run-to-run noise.
    full_reps: list[float] = []
    red_reps: list[float] = []
    for probe in admissible:
        full_reps += [1.0 if x else 0.0 for x in a_full["results"][probe["id"]]]
        red_reps += [1.0 if x else 0.0 for x in a_red["results"][probe["id"]]]

    lost = [
        p["id"]
        for p in admissible
        if sum(a_red["results"][p["id"]]) < sum(a_full["results"][p["id"]])
    ]

    print(f"\n  admissible probes : {len(admissible)}/{len(PROBES)}")
    if full_reps:
        print(
            f"  pass rate  full   : {sum(full_reps) / len(full_reps):.2f}"
            f"  ({int(sum(full_reps))}/{len(full_reps)} reps)"
        )
        print(
            f"  pass rate  reduced: {sum(red_reps) / len(red_reps):.2f}"
            f"  ({int(sum(red_reps))}/{len(red_reps)} reps)"
        )
    print(
        f"  tokens saved      : ~{saved // 4} ({saved}c, "
        f"{100 * saved / a_full['chars']:.0f}% of always-on context)"
    )

    if not admissible:
        accept = False
        print("\n  REJECT -- no admissible probes; the ablation proves nothing.")
    else:
        d = decide(
            Mutation(
                "REMOVE",
                tuple(p["id"] for p in admissible),
                strategy_tag="context-reduction",
            ),
            Measurement(corrections=[0.0] * len(full_reps), success=full_reps),
            Measurement(corrections=[0.0] * len(red_reps), success=red_reps),
            ni_margin=0.10,
        )
        accept = d.outcome == "accepted"
        print(f"\n  {d.outcome.upper()} -- {d.reason}")
        if lost:
            print(f"  (scored lower, not necessarily significantly: {', '.join(lost)})")

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(
            {
                "no_context": a_none,
                "over_determined": [p["id"] for p in over],
                "full": a_full,
                "reduced": a_red,
                "admissible": [p["id"] for p in admissible],
                "inadmissible": inadmissible,
                "lost": lost,
                "chars_saved": saved,
                "accept": accept,
            },
            indent=2,
        )
    )
    print(f"\n  wrote {out}")
    return 0 if accept else 1


if __name__ == "__main__":
    sys.exit(main())
