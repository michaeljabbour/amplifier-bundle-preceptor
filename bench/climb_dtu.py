#!/usr/bin/env python3
"""Wire the calibration loop to real DTU measurement.

`climb.py` is the algorithm and takes an injected `evaluate` callback. This is
that callback, backed by `dtu_run.py`: materialize a candidate instruction set as
an arm, run N isolated container trials, and return the measured series.

Nothing here is a simulation. Every number comes from a real session in a real
container that is destroyed afterwards.

FIRST: THE VALIDITY GATE
------------------------
Before any real climb, the harness must prove it can reject a mutation known to
be bad. If a planted regression is accepted, every subsequent number is
unfalsifiable and the run should be discarded rather than reported. Borrowed from
`amplifier-optimizer-runpod/evals/controls.py`: "if the harness can't detect a
known regression, its wins mean nothing."

    python3 bench/climb_dtu.py --control-only --trials 5    # validity gate
    python3 bench/climb_dtu.py --trials 10                  # full climb

WHAT THE OBJECTIVE IS, AND WHY IT CHANGED
-----------------------------------------
The design assumed correction turns would be the objective. The n=30 run
(2026-08-30) found something more actionable first: composing this bundle costs
+6.9s of session startup (d=6.26), and recording is free. The expensive thing is
LOADING -- modules, agents, context -- not observing.

So the live objective here is `run_s`, session wall-clock. It is measured, large,
and has obvious levers. Correction turns remain the objective for cue work and
`correction_turns.py` is wired and tested; there are simply no earned cues yet,
and inventing some to have something to climb would be authoring a result from
priors -- the exact failure this bundle exists to catch.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from climb import Measurement, Mutation, decide, run_climb
from dtu_run import ARMS, TASKS, run_trial
from splits import split_tasks
from verdict import required_n


def measure(arm: str, tasks: list, trials: int) -> Measurement:
    """Run real trials for one arm and return the measured series.

    `corrections` carries the objective (session seconds -- see the module
    docstring). `success` carries the constraint: 1.0 for a trial that completed
    with the right answer, 0.0 otherwise. Failed launches are dropped from the
    objective but counted as failures in the constraint, so a mutation cannot buy
    a faster mean by crashing the slow trials.
    """
    secs: list[float] = []
    ok: list[float] = []
    for task in tasks:
        for i in range(trials):
            t = run_trial(arm, task, i)
            good = t.launched and t.exit_code == 0 and t.correct
            ok.append(1.0 if good else 0.0)
            if good:
                secs.append(t.run_s)
    return Measurement(corrections=secs, success=ok)


def validity_gate(tasks: list, trials: int) -> bool:
    """Plant a known regression and confirm the accept rule rejects it.

    The planted arm is `observe-off`, which the n=30 run measured at +6.9s
    against baseline -- a real, large, verified regression on the live objective.
    A harness that accepts it cannot detect anything.
    """
    print("=" * 70)
    print("VALIDITY GATE -- can the harness reject a KNOWN regression?")
    print("=" * 70)
    print("  champion  = baseline")
    print("  candidate = observe-off  (measured +6.9s / +138% at n=30)")
    print(f"  running {len(tasks)} tasks x {trials} trials x 2 arms ...\n", flush=True)

    champ = measure("baseline", tasks, trials)
    cand = measure("observe-off", tasks, trials)

    planted = Mutation(
        "ADD",
        ("known-regression",),
        text="Compose the preceptor bundle.",
        origin_obs=("control",),
        strategy_tag="negative-control",
    )
    d = decide(planted, champ, cand, ni_margin=0.05)

    mc = statistics.mean(champ.corrections) if champ.corrections else float("nan")
    mt = statistics.mean(cand.corrections) if cand.corrections else float("nan")
    print(f"  champion  {mc:6.2f}s  (n={len(champ.corrections)})")
    print(f"  candidate {mt:6.2f}s  (n={len(cand.corrections)})")
    print(f"\n  decision: {d.outcome.upper()}")
    print(f"  reason  : {d.reason}")

    passed = d.outcome == "rejected"
    print(
        f"\n  GATE {'PASSED' if passed else 'FAILED'} -- harness "
        f"{'can' if passed else 'CANNOT'} detect a planted regression"
    )
    if not passed:
        print("  Every number from this harness is unfalsifiable. Discard the run.")
    return passed


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--trials", type=int, default=5, help="trials per arm per task")
    ap.add_argument(
        "--tasks", type=int, default=1, help=f"tasks to use (of {len(TASKS)})"
    )
    ap.add_argument(
        "--control-only", action="store_true", help="run the validity gate and stop"
    )
    ap.add_argument("--out", default="bench-results/climb.json")
    args = ap.parse_args()

    splits = split_tasks(list(TASKS), seed=0)
    tasks = (splits.climb or splits.harvest)[: args.tasks] or list(TASKS)[: args.tasks]
    print(
        f"splits: harvest={len(splits.harvest)} climb={len(splits.climb)} "
        f"confirm=SEALED\nusing {len(tasks)} climb task(s), {args.trials} trials each\n"
    )

    if not validity_gate(tasks, args.trials):
        return 2
    if args.control_only:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(json.dumps({"validity_gate": "passed"}, indent=2))
        return 0

    # --- the climb ---------------------------------------------------------
    # The mutation space is the set of arms that can actually be materialized
    # today. With no earned cues there is nothing to ADD or REMOVE from an
    # instruction set, and the honest thing is to say so rather than invent one.
    print("\n" + "=" * 70)
    print("CLIMB")
    print("=" * 70)

    def propose(current: list[str], dead: set[str]) -> list[Mutation]:
        moves = []
        for arm in ARMS:
            if arm == "baseline" or arm in current or arm in dead:
                continue
            moves.append(
                Mutation(
                    "ADD",
                    (arm,),
                    text=f"Compose the {arm} bundle.",
                    origin_obs=("dtu-n30",),
                    strategy_tag=arm,
                )
            )
        return moves

    def evaluate(instr: list[str]) -> Measurement:
        arm = instr[-1] if instr else "baseline"
        return measure(arm, tasks, args.trials)

    r = run_climb(
        [],
        propose,
        evaluate,
        ni_margin=0.02,
        total_loss_budget=0.05,
        max_iterations=3,
        plateau_patience=2,
        log_path=Path("bench-results/climb-trials.jsonl"),
    )

    print(f"\n  champion : {r.champion or '(baseline -- nothing earned its place)'}")
    print(f"  stopped  : {r.stopped_because}")
    print(f"  accepted : {len(r.accepted)} / {len(r.steps)} moves")
    for s in r.steps:
        print(
            f"    {s.mutation['op']:<7} {','.join(s.mutation['cue_ids']):<14} "
            f"{s.decision['outcome']:<9} {s.decision['reason'][:80]}"
        )

    n = args.trials * len(tasks)
    print(f"\n  power: n={n} per arm. Need ~{required_n([1.0] * n, 0.8)} for d=0.8.")

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(
        json.dumps(
            {
                "validity_gate": "passed",
                "champion": r.champion,
                "baseline": r.baseline,
                "stopped_because": r.stopped_because,
                "steps": [
                    {"mutation": s.mutation, "decision": s.decision} for s in r.steps
                ],
                "splits": splits.to_report_dict(),
            },
            indent=2,
            default=str,
        )
    )
    print(f"\n  wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
