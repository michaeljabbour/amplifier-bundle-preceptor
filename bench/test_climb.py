"""Tests for the calibration loop.

The load-bearing tests are the two validity gates:

  test_negative_control_is_rejected   -- if the loop accepts a mutation known to
      be bad, nothing it reports means anything. This is the harness checking
      that it can still detect a regression it planted itself. Borrowed from
      amplifier-optimizer-runpod's controls.py: "if the harness can't detect a
      known regression, its wins mean nothing."

  test_anchor_breach_stops_the_climb   -- individually-safe removals compounding
      into real damage is the specific failure ACE measured (18,282 tok @ 66.7 ->
      122 tok @ 57.1, BELOW the 63.7 no-adaptation baseline). If the anchor does
      not fire, the ratchet runs to the empty prompt.

    uv run --no-project --with pytest pytest bench/test_climb.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

from climb import Measurement, Mutation, admissible, decide, run_climb
from splits import SealedSplitError, split_tasks

NI = 0.05  # non-inferiority margin used throughout these tests


def _m(corr: list[float], succ: list[float] | None = None) -> Measurement:
    return Measurement(corr, succ if succ is not None else [1.0] * len(corr))


def _add(cue: str = "cue-1", **kw) -> Mutation:
    kw.setdefault("origin_obs", ("obs-1",))
    return Mutation("ADD", (cue,), text="Run the tests before declaring done.", **kw)


def _remove(*cues: str) -> Mutation:
    return Mutation("REMOVE", cues or ("cue-1",))


# ---------------------------------------------------------------------------
# Admissibility -- the free gate
# ---------------------------------------------------------------------------


def test_add_without_origin_is_inadmissible():
    """cue-lifecycle.md: a cue enters only from a failure that actually occurred."""
    m = Mutation("ADD", ("cue-9",), text="Always write tests.", origin_obs=())
    ok, why = admissible(m, set())
    assert not ok and "priors" in why


def test_task_specific_edit_is_inadmissible():
    """HarnessCompass's generalization gate: an overfit written INTO the edit
    cannot be caught by measurement, because it measures as a genuine win on the
    set it was written against."""
    for bad in (
        "Make sure test_login passes",
        "Handle the case in auth.py:42",
        "Add a fixture for this",
    ):
        m = Mutation("ADD", ("c",), text=bad, origin_obs=("obs-1",))
        ok, why = admissible(m, set())
        assert not ok, bad
        assert "overfit" in why or "specific" in why


def test_oversized_cue_is_inadmissible():
    m = Mutation("ADD", ("c",), text="x" * 250, origin_obs=("obs-1",))
    ok, why = admissible(m, set())
    assert not ok and "200-char" in why


def test_dead_moves_are_not_retried():
    m = _add(strategy_tag="tests-first")
    ok, why = admissible(m, {"tests-first"})
    assert not ok and "dead move" in why


# ---------------------------------------------------------------------------
# The asymmetry -- the core of the design
# ---------------------------------------------------------------------------


def test_add_requires_superiority():
    """An addition that changes nothing must be struck, not kept."""
    champ = _m([3.0, 3.1, 2.9, 3.0, 3.1, 3.0])
    same = _m([3.0, 3.0, 3.1, 2.9, 3.0, 3.1])
    d = decide(_add(), champ, same, ni_margin=NI)
    assert d.outcome == "rejected"
    assert "superiority" in d.reason


def test_add_accepted_when_it_genuinely_helps():
    champ = _m([3.0, 3.1, 2.9, 3.0, 3.1, 3.0])
    better = _m([1.0, 1.1, 0.9, 1.0, 1.1, 1.0])
    d = decide(_add(), champ, better, ni_margin=NI)
    assert d.outcome == "accepted"
    assert d.delta_corrections < 0


def test_remove_does_not_need_to_improve_anything():
    """The point of a removal is that the instruction was inert. Demanding an
    improvement would reject exactly the removals worth making."""
    champ = _m([3.0, 3.1, 2.9, 3.0, 3.1, 3.0])
    same = _m([3.0, 3.0, 3.1, 2.9, 3.0, 3.1])
    d = decide(_remove(), champ, same, ni_margin=NI)
    assert d.outcome == "accepted"
    assert "non-inferiority met" in d.reason


def test_underpowered_removal_fails_instead_of_passing_by_default():
    """The trap this whole module exists to avoid.

    Two samples per arm cannot rule out harm. A significance test would return
    'not significant' and wave it through; the non-inferiority bound gets WIDER
    with less data, so it fails closed.
    """
    champ = _m([1.0, 1.0], [1.0, 0.5])
    cand = _m([1.0, 1.0], [1.0, 0.5])
    d = decide(_remove(), champ, cand, ni_margin=0.001)
    assert d.outcome == "rejected"
    assert "cannot be ruled out" in d.reason


def test_constraint_checked_before_objective():
    """A mutation must not buy a correction-rate win by paying in task failures."""
    champ = _m([3.0, 3.0, 3.0, 3.0, 3.0, 3.0], [1.0] * 6)
    cand = _m(
        [0.0, 0.0, 0.0, 0.0, 0.0, 0.0], [0.2] * 6
    )  # great corrections, broken tasks
    d = decide(_add(), champ, cand, ni_margin=NI)
    assert d.outcome == "rejected"
    assert "non-inferiority FAILED" in d.reason


def test_remove_rejected_if_corrections_get_worse():
    champ = _m([1.0, 1.0, 1.1, 0.9, 1.0, 1.0])
    worse = _m([3.0, 3.1, 2.9, 3.0, 3.1, 3.0])
    d = decide(_remove(), champ, worse, ni_margin=NI)
    assert d.outcome == "rejected"
    assert "worse" in d.reason


# ---------------------------------------------------------------------------
# Validity gates
# ---------------------------------------------------------------------------


def test_negative_control_is_rejected():
    """THE validity gate. Plant a known-bad mutation; the loop must reject it.

    If this ever passes a bad move, every other number the harness produces is
    unfalsifiable and the run should be discarded rather than reported.
    """
    champ = _m([1.0, 1.0, 1.1, 0.9, 1.0, 1.0], [1.0] * 6)
    sabotage = _m([5.0, 5.2, 4.8, 5.0, 5.1, 5.0], [0.3] * 6)
    d = decide(_add(), champ, sabotage, ni_margin=NI)
    assert d.outcome == "rejected", "harness cannot detect a planted regression"


def test_anchor_breach_stops_the_climb():
    """Individually-safe moves compounding into real damage must halt the loop.

    Success decays 0.02 per accepted move -- under the 0.05 margin every time, so
    no single decision is refusable. Only the anchor, which compares against the
    ORIGINAL baseline rather than the current champion, can catch it.
    """
    state = {"succ": 1.0}

    def evaluate(instr: list[str]) -> Measurement:
        # Degrade with each removal; corrections stay flat so only the
        # constraint side can object.
        state["succ"] = 1.0 - 0.02 * (5 - len(instr))
        s = max(0.0, state["succ"])
        return Measurement([2.0] * 8, [s] * 8)

    def propose(current: list[str], dead: set[str]) -> list[Mutation]:
        return [
            Mutation("REMOVE", (c,), strategy_tag=f"drop-{c}")
            for c in current
            if f"drop-{c}" not in dead
        ]

    r = run_climb(
        ["c1", "c2", "c3", "c4", "c5"],
        propose,
        evaluate,
        ni_margin=0.05,  # each move individually passes
        total_loss_budget=0.05,  # but the RUN may only lose this much in total
        max_iterations=10,
        anchor_every=3,
    )
    assert r.anchor_checks, "anchor never ran"
    assert "ANCHOR BREACH" in r.stopped_because
    assert r.anchor_checks[-1]["drifted"] is True


def test_climb_returns_baseline_when_nothing_improves():
    """Monotone-safe: if no mutation earns its place, the baseline is returned."""

    def evaluate(_: list[str]) -> Measurement:
        return Measurement([2.0, 2.1, 1.9, 2.0, 2.1, 2.0], [1.0] * 6)

    def propose(current: list[str], dead: set[str]) -> list[Mutation]:
        m = Mutation(
            "ADD",
            ("new",),
            text="Do a good job.",
            origin_obs=("obs-1",),
            strategy_tag="vague",
        )
        return [] if "vague" in dead else [m]

    r = run_climb(
        ["c1"], propose, evaluate, ni_margin=NI, total_loss_budget=NI, max_iterations=4
    )
    assert r.champion == ["c1"]
    assert not r.accepted


def test_rejection_without_a_reason_is_refused(tmp_path):
    """design_ledger's discipline: a failure recorded without a cause makes the
    dead-move set superstition rather than evidence."""
    from climb import Decision, Step, _record

    bad = Step(1, {}, {"outcome": "rejected", "reason": ""}, 0)
    with pytest.raises(ValueError, match="no reason"):
        _record(tmp_path / "log.jsonl", bad)

    good = Step(1, {}, Decision("rejected", "because X").__dict__, 0)
    _record(tmp_path / "log.jsonl", good)
    assert (tmp_path / "log.jsonl").read_text().count("\n") == 1


# ---------------------------------------------------------------------------
# Splits
# ---------------------------------------------------------------------------


def test_confirm_split_is_sealed():
    s = split_tasks([f"t{i}" for i in range(10)], seed=1)
    with pytest.raises(SealedSplitError):
        _ = s.confirm
    assert s.unseal_for_gate("final report")
    assert s.confirm


def test_splits_are_disjoint_and_deterministic():
    a = split_tasks([f"t{i}" for i in range(20)], seed=7)
    b = split_tasks([f"t{i}" for i in range(20)], seed=7)
    assert a.harvest == b.harvest and a.climb == b.climb
    all_ = a.harvest + a.climb + a.unseal_for_gate("test")
    assert len(all_) == len(set(all_)) == 20, "splits must partition, not overlap"


def test_unseal_is_logged_every_time():
    s = split_tasks([f"t{i}" for i in range(9)], seed=3)
    s.unseal_for_gate("first")
    s.unseal_for_gate("second")
    assert s.to_report_dict()["confirm_access_count"] == 2, (
        "a run that peeked repeatedly must be visible"
    )
