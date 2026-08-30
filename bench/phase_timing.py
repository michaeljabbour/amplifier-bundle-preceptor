#!/usr/bin/env python3
"""Time bundle load / prepare / mount directly. No LLM anywhere in the path.

WHY THIS EXISTS
---------------
Wall-clock of `amplifier run` cannot resolve bundle cost. Proven, not assumed:
a 4-arm control at n=10 put preceptor's marginal cost at **-3.91s** against a
foundation-only control. A bundle that *includes* foundation cannot load faster
than foundation. The quantity of interest was buried under LLM latency, and the
measurement was returning noise with a confident sign.

Three artifacts in a row came out of that proxy:
  1. cold git resolution counted as bundle cost   -> fabricated +74%
  2. warming only treatment arms                  -> fabricated 3.5x speedup
  3. `--bundle <url>` flag cost counted as bundle -> fabricated +138%

Each had overwhelming statistics behind it (d up to 7.4, t up to 28.5). The
common failure was not statistical -- it was measuring a proxy that contained a
larger, arm-correlated term than the thing being measured.

So: measure the phases directly, in-process, with no network call and no model.

    python3 bench/phase_timing.py --reps 20

WHAT IS MEASURED
----------------
  load     load_bundle(uri)      resolution + parse + include expansion
  prepare  bundle.prepare()      module download / install / activation
  mount    create_session()      the actual mount() calls

`load` is cached after the first rep, so rep 0 is discarded as warm-up. What
remains is the steady-state cost a user pays on every session start.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from verdict import compare

FOUNDATION = "git+https://github.com/microsoft/amplifier-foundation@main"
PRECEPTOR = "git+https://github.com/michaeljabbour/amplifier-bundle-preceptor@main"

TARGETS: dict[str, str] = {
    "foundation": FOUNDATION,
    "observe-off": f"{PRECEPTOR}#subdirectory=bundles/observe-only.yaml",
    "observe-on": f"{PRECEPTOR}#subdirectory=bundles/observe-on.yaml",
}


def _context_chars(prepared) -> int:
    """Total characters of always-on context the bundle injects.

    Mount cost is paid once per session. Context is paid on EVERY request for the
    life of the session, so for a context bundle this is the cost that compounds.
    Counted from resolved context content when the prepared bundle exposes it,
    else from the files the mount plan names.
    """
    total = 0
    plan = getattr(prepared, "mount_plan", {}) or {}
    ctx = plan.get("context")
    if isinstance(ctx, str):
        return len(ctx)
    entries = ctx if isinstance(ctx, list) else []
    for e in entries:
        if isinstance(e, str):
            total += len(e) if "\n" in e else _file_chars(e)
        elif isinstance(e, dict):
            for k in ("content", "text", "body"):
                if isinstance(e.get(k), str):
                    total += len(e[k])
                    break
            else:
                for k in ("path", "file", "source", "include"):
                    if isinstance(e.get(k), str):
                        total += _file_chars(e[k])
                        break
    return total


def _file_chars(path: str) -> int:
    try:
        pp = Path(path).expanduser()
        return (
            len(pp.read_text(encoding="utf-8", errors="replace")) if pp.is_file() else 0
        )
    except OSError:
        return 0


async def time_phases(uri: str) -> dict[str, float] | None:
    """One rep: load, prepare, mount. Returns seconds per phase."""
    from amplifier_foundation import load_bundle

    try:
        t0 = time.perf_counter()
        b = await load_bundle(uri)
        t1 = time.perf_counter()
        p = await b.prepare()
        t2 = time.perf_counter()
        s = await p.create_session()
        t3 = time.perf_counter()
    except Exception as e:  # noqa: BLE001 - a failed rep is data, not a crash
        print(f"    rep failed: {type(e).__name__}: {e}", file=sys.stderr)
        return None

    try:
        n_hooks = len(p.mount_plan.get("hooks", []))
        n_tools = len(p.mount_plan.get("tools", []))
        ctx_chars = _context_chars(p)
    except Exception:  # noqa: BLE001
        n_hooks = n_tools = -1
        ctx_chars = -1
    finally:
        if hasattr(s, "cleanup"):
            try:
                await s.cleanup()
            except Exception as e:  # noqa: BLE001 - cleanup failure must not void the rep
                print(f"    cleanup: {type(e).__name__}", file=sys.stderr)

    return {
        "ctx_chars": ctx_chars,
        "load": t1 - t0,
        "prepare": t2 - t1,
        "mount": t3 - t2,
        "total": t3 - t0,
        "hooks": n_hooks,
        "tools": n_tools,
    }


async def run(reps: int) -> dict:
    out: dict[str, list[dict]] = {}
    for name, uri in TARGETS.items():
        print(f"  {name} ...", flush=True)
        reps_data: list[dict] = []
        for i in range(reps + 1):  # +1: rep 0 is warm-up, discarded
            r = await time_phases(uri)
            if r and i > 0:
                reps_data.append(r)
        out[name] = reps_data
        if reps_data:
            m = statistics.mean(d["total"] for d in reps_data)
            print(
                f"    n={len(reps_data)}  total={m:.3f}s  "
                f"hooks={reps_data[0]['hooks']} tools={reps_data[0]['tools']}",
                flush=True,
            )
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reps", type=int, default=20)
    ap.add_argument("--out", default="phase-timing.json")
    args = ap.parse_args()

    print(
        f"phase timing: {len(TARGETS)} bundles x {args.reps} reps (+1 warm-up each)\n"
    )
    data = asyncio.run(run(args.reps))

    print("\n" + "=" * 74)
    print(f"{'bundle':<14} {'load':>16} {'prepare':>16} {'mount':>16} {'total':>10}")
    print("-" * 74)
    summary: dict = {}
    for name, reps in data.items():
        if not reps:
            print(f"{name:<14} (no successful reps)")
            continue
        row = {}
        for ph in ("load", "prepare", "mount", "total"):
            xs = [d[ph] for d in reps]
            row[ph] = {
                "mean": statistics.mean(xs),
                "sd": statistics.stdev(xs) if len(xs) > 1 else 0.0,
                "n": len(xs),
            }
        summary[name] = row | {
            "hooks": reps[0]["hooks"],
            "tools": reps[0]["tools"],
            "ctx_chars": reps[0]["ctx_chars"],
            "ctx_tokens_est": reps[0]["ctx_chars"] // 4,
        }
        print(
            f"{name:<14} "
            f"{row['load']['mean']:>7.3f}+/-{row['load']['sd']:<6.3f} "
            f"{row['prepare']['mean']:>7.3f}+/-{row['prepare']['sd']:<6.3f} "
            f"{row['mount']['mean']:>7.3f}+/-{row['mount']['sd']:<6.3f} "
            f"{row['total']['mean']:>9.3f}"
        )

    # The contrast that matters: preceptor vs foundation, same mechanism both sides.
    print("\n" + "=" * 74)
    print("PRECEPTOR'S MARGINAL COST vs foundation (same load path, different payload)")
    print("=" * 74)
    base = data.get("foundation") or []
    for name in ("observe-off", "observe-on"):
        reps = data.get(name) or []
        if not base or not reps:
            continue
        print(f"\n  {name}")
        for ph in ("load", "prepare", "mount", "total"):
            r = compare([d[ph] for d in base], [d[ph] for d in reps])
            print(f"    {ph:<9} {r.verdict:<13} {r.detail}")
        summary.setdefault(name, {})["vs_foundation"] = {
            ph: compare([d[ph] for d in base], [d[ph] for d in reps]).__dict__
            for ph in ("load", "prepare", "mount", "total")
        }

    Path(args.out).write_text(json.dumps(summary, indent=2, default=str))
    print(f"\nwrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
