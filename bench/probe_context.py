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

    a_full = run_arm(args.container, "full", full, args.reps)
    a_red = run_arm(args.container, "reduced", reduced, args.reps)

    print("\n" + "=" * 70)
    print("VERDICT")
    print("=" * 70)
    admissible = [p for p in PROBES if all(a_full["results"][p["id"]])]
    inadmissible = [p["id"] for p in PROBES if p not in admissible]
    if inadmissible:
        print(
            f"  EXCLUDED (full context already fails these): {', '.join(inadmissible)}"
        )
        print("  A probe the full context fails measures a gap, not a loss.")

    lost = [p["id"] for p in admissible if not all(a_red["results"][p["id"]])]
    saved = a_full["chars"] - a_red["chars"]

    print(f"\n  admissible probes : {len(admissible)}/{len(PROBES)}")
    print(f"  preserved         : {len(admissible) - len(lost)}/{len(admissible)}")
    print(
        f"  tokens saved      : ~{saved // 4} ({saved}c, "
        f"{100 * saved / a_full['chars']:.0f}% of always-on context)"
    )

    accept = not lost and admissible
    if lost:
        print(f"\n  LOST: {', '.join(lost)}")
        print(
            "  REJECT -- the reduction removed something the full context provably enabled."
        )
    elif not admissible:
        print("\n  REJECT -- no admissible probes; the ablation proves nothing.")
    else:
        print(
            f"\n  ACCEPT -- every admissible probe survived, ~{saved // 4} tokens/request saved."
        )

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(
            {
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
