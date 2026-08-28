"""Property tests for the single invariant gates.py exists to protect: promote()
and retire() must never both accept the same evidence, plus the autonomy lock
preconditions."""

from __future__ import annotations

import itertools

from amplifier_module_tool_preceptor import gates

_VERDICTS = ("positive", "no-effect", "inconclusive")
_N_PER_ARM_RANGE = range(11)
_MEAN_SIGNS = (-1, 0, 1)


def test_promote_and_retire_are_mutually_exclusive():
    """Enumerate the evidence space (verdict x n_per_arm x sign of mean delta) and
    assert not (promote(a) and retire(a)) for every tuple. This is the single
    invariant the whole module exists to protect -- see gates.py's module docstring
    and context/methodology/cue-lifecycle.md."""
    checked = 0
    for verdict, n_per_arm, sign in itertools.product(
        _VERDICTS, _N_PER_ARM_RANGE, _MEAN_SIGNS
    ):
        assessment = {
            "verdict": verdict,
            "n_per_arm": n_per_arm,
            "mean": sign * 1.0,
            "variance": 0.1,
        }
        assert not (gates.promote(assessment) and gates.retire(assessment)), (
            f"promote() and retire() both accepted {assessment!r}"
        )
        checked += 1
    assert checked == len(_VERDICTS) * len(_N_PER_ARM_RANGE) * len(_MEAN_SIGNS)


def test_inconclusive_satisfies_neither():
    assessment = {
        "verdict": "inconclusive",
        "n_per_arm": 20,
        "mean": 1.0,
        "variance": 0.01,
    }
    assert gates.promote(assessment) is False
    assert gates.retire(assessment) is False


def test_underpowered_positive_does_not_promote():
    assessment = {"verdict": "positive", "n_per_arm": 4, "mean": 1.0, "variance": 0.01}
    assert gates.promote(assessment) is False


def _base_state() -> dict:
    return {
        "fade_attempts": 40,
        "shadow_restores": 0,
        "false_fade_rate": 0.0,
        "detector_calibrated": True,
    }


def _base_cfg() -> dict:
    return {"autonomous": True, "min_fade_attempts": 40, "false_fade_ceiling": 0.10}


def test_autonomy_locked_by_default():
    unlocked, reason = gates.autonomy_unlocked({}, {})
    assert unlocked is False
    assert reason


def test_autonomy_unlocked_when_all_conditions_met():
    unlocked, _reason = gates.autonomy_unlocked(_base_state(), _base_cfg())
    assert unlocked is True


def test_autonomy_locked_when_not_autonomous():
    cfg = {**_base_cfg(), "autonomous": False}
    unlocked, reason = gates.autonomy_unlocked(_base_state(), cfg)
    assert unlocked is False
    assert "autonomous" in reason


def test_autonomy_locked_when_detector_not_calibrated():
    state = {**_base_state(), "detector_calibrated": False}
    unlocked, reason = gates.autonomy_unlocked(state, _base_cfg())
    assert unlocked is False
    assert "detector_calibrated" in reason


def test_autonomy_locked_when_below_min_fade_attempts():
    state = {**_base_state(), "fade_attempts": 10}
    unlocked, reason = gates.autonomy_unlocked(state, _base_cfg())
    assert unlocked is False
    assert "fade_attempts" in reason


def test_autonomy_locked_when_false_fade_rate_at_ceiling():
    state = {**_base_state(), "false_fade_rate": 0.10}
    unlocked, reason = gates.autonomy_unlocked(state, _base_cfg())
    assert unlocked is False
    assert "false_fade_rate" in reason


def test_false_fade_rate_relocks():
    """Pushing the rate above the ceiling re-locks -- this is correct behavior,
    not a bug (cue-lifecycle.md, 'Autonomy is earned')."""
    state = _base_state()
    cfg = _base_cfg()
    unlocked, _reason = gates.autonomy_unlocked(state, cfg)
    assert unlocked is True

    state["shadow_restores"] = 5
    state["false_fade_rate"] = gates.compute_false_fade_rate(
        state["shadow_restores"], state["fade_attempts"]
    )
    unlocked, reason = gates.autonomy_unlocked(state, cfg)
    assert unlocked is False
    assert "false_fade_rate" in reason
