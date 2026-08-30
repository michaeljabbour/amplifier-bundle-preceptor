#!/usr/bin/env python3
"""Bidirectional hill-climbing calibration for an instruction set.

Proposes mutations (ADD a cue earned from an observed failure, REMOVE a batch of
existing instructions), evaluates each against the `climb` split, and accepts
only what survives a pre-registered statistical rule. Objective: minimize
developer-correction turns subject to no regression in task success.

WHY THE ACCEPT RULE IS ASYMMETRIC
---------------------------------
Textbook hill climbing uses one threshold for every move. That is wrong here,
and the arithmetic says so out loud.

An ADD asks "did this help?" -- a superiority test. H0: delta <= 0.
A REMOVE asks "did this do no harm?" -- which is *failure to reject* a null, and
failure to reject is not evidence of absence.

The trap: if you budget m removals against a total tolerable loss of Delta_total,
each removal gets margin delta <= Delta_total / m. Required n scales as 1/delta^2.
Concretely, Delta_total = 5pp over m = 10 single removals gives delta = 0.5pp, and
at alpha=.05, beta=.20, discordance .15 that is ~37,000 paired evaluations PER
REMOVAL. Single-move removal hill climbing is not expensive; it is impossible.

So removals are BATCHED. One candidate set of 10 tested at delta = 5pp needs ~100x
fewer samples than 10 removals at 0.5pp each. This mirrors HarnessCompass's
component-wise optimization "before consolidating them into a unified harness."

Note also that multiple-comparison correction is actively HARMFUL on the removal
side: shrinking alpha makes harm *harder* to detect, so more removals sail through.
Bonferroni is the right instinct pointed the wrong way.

WHY THE LOOP IS MONOTONE-SAFE
-----------------------------
Two states, following RSEA (arXiv:2606.28374):
  working  -- accepts laterally (>=), so the search can cross plateaus
  champion -- updates strictly (>), so the returned artifact never underperforms
              the null. If nothing strictly improves, this returns the baseline.

RSEA's own ablation: without the held-out gate, in-sample hits 100.0 while test
sits at 66.7 -- a 33-point gap. And their warning aimed exactly at this design:
"with a non-strict best-update, a candidate that merely ties on a small val draw
can be frozen and then hurt on test." Removals tie. That is what they do.

THE RATCHET
-----------
A remove-capable climber where removals are accepted on "no measured harm" is a
ratchet pointed at the empty prompt: additions must clear a bar, removals only
have to fail to trip an alarm. ACE (arXiv:2510.04618) measured where that ends --
context collapsed 18,282 tokens @ 66.7 accuracy to 122 tokens @ 57.1, *below* the
63.7 no-adaptation baseline. Defenses here: batched removals, a non-inferiority
margin rather than a significance test, and an anchor re-check against the
ORIGINAL baseline every `anchor_every` accepts to catch compounded damage that no
individual decision was large enough to reveal.

WHAT THIS DOES NOT DO
---------------------
It does not trust an LLM's prediction about its own edits. AHE (arXiv:2604.25850)
measured an evolver predicting its own regressions at 11.8% precision / 11.1%
recall -- roughly 2x chance. Predicted-no-harm is logged as a falsifiable contract
and is never a gate.
"""

from __future__ import annotations

import json
import math
import re
import sys
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

sys.path.insert(0, str(Path(__file__).parent))
from verdict import compare  # ONE implementation of the stats

Op = Literal["ADD", "REMOVE"]
Outcome = Literal["accepted", "rejected", "invalid"]


# ---------------------------------------------------------------------------
# Moves
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Mutation:
    """One proposed change to the instruction set.

    A REMOVE carries a LIST of cue ids, not one. See the module docstring: single
    removals are not statistically affordable at any realistic budget.
    """

    op: Op
    cue_ids: tuple[str, ...]
    text: str | None = None  # ADD only
    origin_obs: tuple[str, ...] = ()  # observation ids this is traceable to
    strategy_tag: str = ""  # for the dead-move set
    predicted_effect: str = ""  # falsifiable contract, NEVER a gate

    @property
    def key(self) -> str:
        return f"{self.op}:{','.join(sorted(self.cue_ids))}"


@dataclass
class Measurement:
    """What an evaluation of one instruction set returns.

    `corrections` is the objective (lower is better). `success` is the constraint
    (higher is better). Both are per-task series so the stats are paired.
    """

    corrections: list[float]
    success: list[float]

    def __len__(self) -> int:
        return len(self.corrections)


@dataclass
class Decision:
    outcome: Outcome
    reason: str  # MANDATORY. See _record().
    objective_verdict: str = ""
    constraint_verdict: str = ""
    delta_corrections: float = 0.0
    delta_success: float = 0.0
    ni_upper_bound: float | None = None


# ---------------------------------------------------------------------------
# Admissibility -- the cheapest gate, applied before any rollout is spent
# ---------------------------------------------------------------------------

# HarnessCompass (arXiv:2608.01918) reports that a content/placement gate alone
# bought +6.8pp held-out in 2 turns, for ZERO extra rollouts, by shrinking the
# space of proposable edits so the search cannot express an overfit. It is the
# highest-leverage thing in this file and it costs nothing.
_TASK_SPECIFIC = re.compile(
    r"\b(?:test_\w+|task[-_ ]?\d+|instance[-_ ]?\d+|"
    r"\w+\.py:\d+|def test|assert\w*\(|"
    r"fixture|conftest)\b",
    re.IGNORECASE,
)


def admissible(m: Mutation, dead: set[str]) -> tuple[bool, str]:
    """Reject a mutation before spending a single trial on it.

    Three rules, cheapest first:
      1. Already tried and failed for this signature (the dead-move set).
      2. Names a specific task, test, or file under evaluation -- that is an
         overfit expressed directly in the edit, and no amount of measurement
         will detect it because it will measure as a genuine win on the set it
         was written against.
      3. An ADD with no traceable origin observation. `cue-lifecycle.md`: a cue
         enters only from a failure that actually occurred.
    """
    if m.key in dead or (m.strategy_tag and m.strategy_tag in dead):
        return (
            False,
            f"dead move: {m.strategy_tag or m.key} already failed for this signature",
        )

    if m.op == "ADD":
        if not m.origin_obs:
            return (
                False,
                "ADD with no origin observations -- a cue authored from priors, not evidence",
            )
        if m.text and _TASK_SPECIFIC.search(m.text):
            return False, (
                "names a specific task/test/file under evaluation -- this is an "
                "overfit written into the edit, which measurement cannot catch"
            )
        if m.text and len(m.text) > 200:
            return False, f"cue text {len(m.text)} chars exceeds the 200-char ceiling"
    return True, ""


# ---------------------------------------------------------------------------
# The accept rule
# ---------------------------------------------------------------------------


def _noninferiority_upper_bound(
    control: Sequence[float], treat: Sequence[float], alpha: float = 0.05
) -> float:
    """One-sided upper confidence bound on the LOSS (control_mean - treat_mean).

    Positive means the treatment is worse. Non-inferiority is established when
    this bound sits below the pre-registered margin -- i.e. we are confident the
    damage, if any, is smaller than what we agreed to tolerate.

    This is deliberately NOT "the drop was not significant". A tiny sample makes
    any drop non-significant, which is how an underpowered test launders harm
    into permission. The bound gets WIDER with less data, so a small sample fails
    the test instead of passing it by default.
    """
    nc, nt = len(control), len(treat)
    if nc < 2 or nt < 2:
        return math.inf
    mc = sum(control) / nc
    mt = sum(treat) / nt
    vc = sum((x - mc) ** 2 for x in control) / (nc - 1)
    vt = sum((x - mt) ** 2 for x in treat) / (nt - 1)
    se = math.sqrt(vc / nc + vt / nt)
    if se == 0:
        return mc - mt
    z = 1.645 if alpha <= 0.05 else 1.282  # one-sided
    return (mc - mt) + z * se


def decide(
    m: Mutation,
    champion: Measurement,
    candidate: Measurement,
    *,
    ni_margin: float,
    alpha: float = 0.05,
) -> Decision:
    """The pre-registered accept rule. Asymmetric by design.

    Order matters and mirrors design-loop's MACA discipline: the CONSTRAINT is
    checked before the objective, so a mutation cannot buy a correction-rate win
    by paying for it in task failures.
    """
    if len(champion) < 2 or len(candidate) < 2:
        return Decision(
            "invalid",
            f"insufficient trials: champion n={len(champion)}, candidate n={len(candidate)}",
        )

    # --- Constraint: task success must not regress beyond the margin ---------
    ni_bound = _noninferiority_upper_bound(champion.success, candidate.success, alpha)
    d_success = (sum(candidate.success) / len(candidate.success)) - (
        sum(champion.success) / len(champion.success)
    )

    if ni_bound >= ni_margin:
        return Decision(
            "rejected",
            (
                f"non-inferiority FAILED on task success: upper bound on loss "
                f"{ni_bound:+.4f} >= margin {ni_margin:.4f}. Not proof of harm -- "
                f"proof that harm this large cannot be ruled out at n={len(candidate)}."
            ),
            constraint_verdict="non-inferior: no",
            delta_success=d_success,
            ni_upper_bound=ni_bound,
        )

    # --- Objective: correction turns. Lower is better, so we want delta < 0. --
    obj = compare(champion.corrections, candidate.corrections)
    d_corr = obj.delta

    if m.op == "ADD":
        # Superiority. An addition must EARN its place.
        if obj.verdict == "positive" and d_corr < 0:
            return Decision(
                "accepted",
                f"superiority met: corrections {d_corr:+.3f} ({obj.detail})",
                obj.verdict,
                "non-inferior: yes",
                d_corr,
                d_success,
                ni_bound,
            )
        return Decision(
            "rejected",
            (
                f"ADD failed superiority: {obj.verdict} ({obj.detail}). "
                "An addition that cannot show a positive effect is unearned scaffolding."
            ),
            obj.verdict,
            "non-inferior: yes",
            d_corr,
            d_success,
            ni_bound,
        )

    # REMOVE: non-inferiority on the constraint is already established above.
    # We do NOT additionally require the removal to improve corrections -- the
    # point of a removal is that the instruction was not doing anything, and
    # demanding an improvement would reject exactly the removals we want.
    #
    # But we DO reject a removal that measurably makes corrections worse, even
    # within the success margin, because that is the ratchet failing loudly.
    if obj.verdict == "positive" and d_corr > 0:
        return Decision(
            "rejected",
            f"REMOVE made corrections significantly worse: {d_corr:+.3f} ({obj.detail})",
            obj.verdict,
            "non-inferior: yes",
            d_corr,
            d_success,
            ni_bound,
        )
    return Decision(
        "accepted",
        (
            f"non-inferiority met: upper bound on success loss {ni_bound:+.4f} < "
            f"margin {ni_margin:.4f}; corrections {d_corr:+.3f} ({obj.verdict})"
        ),
        obj.verdict,
        "non-inferior: yes",
        d_corr,
        d_success,
        ni_bound,
    )


# ---------------------------------------------------------------------------
# The loop
# ---------------------------------------------------------------------------


@dataclass
class Step:
    iteration: int
    mutation: dict
    decision: dict
    champion_size: int
    ts: str = field(default_factory=lambda: datetime.now(UTC).isoformat())


@dataclass
class ClimbResult:
    champion: list[str]
    baseline: list[str]
    steps: list[Step]
    stopped_because: str
    anchor_checks: list[dict] = field(default_factory=list)
    control_detected: bool | None = None

    @property
    def accepted(self) -> list[Step]:
        return [s for s in self.steps if s.decision["outcome"] == "accepted"]


def run_climb(
    baseline: list[str],
    propose: Callable[[list[str], set[str]], list[Mutation]],
    evaluate: Callable[[list[str]], Measurement],
    *,
    ni_margin: float,
    total_loss_budget: float,
    max_iterations: int = 8,
    plateau_patience: int = 2,
    anchor_every: int = 3,
    log_path: Path | None = None,
) -> ClimbResult:
    """Champion/challenger climb over instruction sets.

    `propose(current, dead)` returns candidate mutations ranked cheapest-first --
    the ledger's own opportunity/violation counters are the intended ranking
    heuristic. Counters RANK; measurement DECIDES. That split is what keeps an
    uncalibrated counter from gating anything.

    `evaluate(instruction_set)` runs trials and returns a Measurement. It should
    read from the CLIMB split only; the confirm split stays sealed until after
    this returns.

    TWO budgets, and the distinction is the whole point of the anchor:

      ni_margin          per-move tolerance. What one mutation may cost.
      total_loss_budget  FIXED total tolerance across the entire run.

    The relationship the literature forces is `ni_margin <= total_loss_budget / m`
    for m planned accepts. If the anchor's budget were instead allowed to grow
    with the accept count, it would expand to accommodate whatever damage had
    already accumulated and could never fire -- which is precisely the bug the
    anchor exists to catch, committed by the anchor itself. (An earlier draft of
    this function had exactly that defect; `test_anchor_breach_stops_the_climb`
    is what found it.)
    """
    if ni_margin > total_loss_budget:
        raise ValueError(
            f"per-move margin {ni_margin} exceeds the total budget {total_loss_budget}: "
            "a single mutation could spend the whole run's tolerance"
        )
    champion = list(baseline)
    champion_m = evaluate(champion)
    baseline_m = champion_m  # frozen: the anchor compares against THIS, always
    dead: set[str] = set()
    steps: list[Step] = []
    anchors: list[dict] = []
    consecutive_rejects = 0
    stopped = "max_iterations reached"

    for it in range(1, max_iterations + 1):
        moves = propose(champion, dead)
        if not moves:
            stopped = "proposer returned no admissible moves"
            break

        progressed = False
        for m in moves:
            ok, why = admissible(m, dead)
            if not ok:
                steps.append(
                    Step(it, asdict(m), asdict(Decision("invalid", why)), len(champion))
                )
                dead.add(m.strategy_tag or m.key)
                continue

            candidate = _apply(champion, m)
            cand_m = evaluate(candidate)
            d = decide(m, champion_m, cand_m, ni_margin=ni_margin)
            steps.append(Step(it, asdict(m), asdict(d), len(champion)))
            _record(log_path, steps[-1])

            if d.outcome == "accepted":
                champion, champion_m = candidate, cand_m
                consecutive_rejects = 0
                progressed = True
                break  # first-improvement: steepest-ascent costs K*n per iteration
            dead.add(m.strategy_tag or m.key)

        if not progressed:
            consecutive_rejects += 1
            if consecutive_rejects >= plateau_patience:
                stopped = f"plateau: {consecutive_rejects} consecutive iterations with no accepted move"
                break

        # Anchor re-check against the ORIGINAL baseline. Detects compounded
        # damage that no individual decision was large enough to reveal -- the
        # failure mode ACE measured as context collapse.
        n_acc = len([s for s in steps if s.decision["outcome"] == "accepted"])
        if n_acc and n_acc % anchor_every == 0:
            bound = _noninferiority_upper_bound(baseline_m.success, champion_m.success)
            # FIXED budget. Not n_acc * ni_margin -- see the docstring.
            cumulative = total_loss_budget
            drifted = bound >= cumulative
            anchors.append(
                {
                    "after_accepts": n_acc,
                    "upper_bound_vs_baseline": bound,
                    "cumulative_budget": cumulative,
                    "drifted": drifted,
                }
            )
            if drifted:
                stopped = (
                    f"ANCHOR BREACH after {n_acc} accepts: cumulative loss vs. the "
                    f"ORIGINAL baseline ({bound:+.4f}) exceeds the total budget "
                    f"({cumulative:.4f}). Every move passed its own margin of "
                    f"{ni_margin:.4f}; together they did not."
                )
                break

    return ClimbResult(champion, baseline, steps, stopped, anchors)


def _apply(current: list[str], m: Mutation) -> list[str]:
    if m.op == "ADD":
        return [*current, m.cue_ids[0]]
    drop = set(m.cue_ids)
    return [c for c in current if c not in drop]


def _record(path: Path | None, step: Step) -> None:
    """Append one decision. A rejection MUST carry a reason.

    Borrowed from design_ledger, which refuses to write a non-accepted record
    without a `reject_reason`. That constraint is what makes a dead-move set
    trustworthy rather than a pile of superstition -- "we tried X and it didn't
    work" is unfalsifiable without the why.
    """
    if path is None:
        return
    if step.decision["outcome"] != "accepted" and not step.decision.get("reason"):
        raise ValueError("refusing to log a non-accepted decision with no reason")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(asdict(step), default=str) + "\n")
