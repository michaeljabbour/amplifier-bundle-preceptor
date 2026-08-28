"""Tests for the correction-turn metric.

The load-bearing test here is `test_platform_machinery_is_not_a_correction`.
On first contact with real transcripts this tool scored 6 corrections in a
session that had 3, because `<system-reminder>` and `<turn_aborted>` blocks
arrive with role=user and got classified as "redirect". That inflates every
arm of an A/B and, worse, inflates them by an amount that depends on how much
platform machinery fired -- which is not constant across arms. It would have
looked like a real effect.

    uv run --no-project --with pytest pytest bench/test_correction_turns.py -q
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from correction_turns import analyze, classify, human_text


def _write(tmp_path: Path, *messages: dict) -> Path:
    p = tmp_path / "transcript.jsonl"
    p.write_text("\n".join(json.dumps(m) for m in messages), encoding="utf-8")
    return p


def _user(text: str) -> dict:
    return {"role": "user", "content": text}


def _asst(text: str = "ok") -> dict:
    return {"role": "assistant", "content": text}


# --------------------------------------------------------------------------
# Classification
# --------------------------------------------------------------------------


def test_nudges_from_the_ai_user_vocabulary():
    """These are the literal strings ai_user.py:122-129 tells it to send."""
    for t in ("go ahead", "yes", "proceed", "ok", "sure", "yep", "continue"):
        assert classify(t) == "nudge", t


def test_redirect_beats_a_leading_acknowledgement():
    """'ok, but no, don't X' is a redirect that opens with an ack.

    Order matters in classify(): matching NUDGE first would bucket this as the
    cheapest class, which is exactly backwards -- it is the most expensive one.
    """
    assert classify("ok but no, don't touch the config") == "redirect"
    assert classify("sure, though actually use pytest instead") == "redirect"


def test_redirect_catches_rework_language():
    for t in (
        "no, use pytest instead",
        "that's not what I asked",
        "you forgot the tests",
        "still failing",
        "revert that",
        "try again",
    ):
        assert classify(t) == "redirect", t


def test_unmatched_text_is_substantive_not_dropped():
    """The safe default. An undercount makes an arm look better than it is."""
    assert classify("Add rate limiting to the login endpoint") == "substantive"


# --------------------------------------------------------------------------
# The regression that matters
# --------------------------------------------------------------------------


def test_platform_machinery_is_not_a_correction(tmp_path):
    """Regression: caught on real transcripts, inflated a session 3 -> 6."""
    p = _write(
        tmp_path,
        _user("build the thing"),
        _asst(),
        _user(
            '<system-reminder source="amplifier-studio-project-plan">\nUse X\n</system-reminder>'
        ),
        _asst(),
        _user("<turn_aborted>\nThe user intentionally interrupted the previous turn."),
        _asst(),
        _user("<tool_result>output here</tool_result>"),
        _asst(),
        _user("no, use pytest instead"),
    )
    r = analyze(p)
    assert r.user_turns == 2, "only the opening request and the real redirect are human"
    assert r.correction_turns == 1
    assert r.counts["redirect"] == 1


def test_reminder_appended_to_a_real_turn_survives():
    """The opposite error, and just as bad.

    A genuine correction with a reminder stapled to it must still count --
    stripping the block must not discard the turn.
    """
    t = human_text(
        _user(
            'no, use pytest instead\n<system-reminder source="x">noise</system-reminder>'
        )
    )
    assert t == "no, use pytest instead"
    assert classify(t) == "redirect"


# --------------------------------------------------------------------------
# Counting
# --------------------------------------------------------------------------


def test_opening_request_is_not_a_correction(tmp_path):
    p = _write(tmp_path, _user("build the thing"), _asst())
    r = analyze(p)
    assert r.user_turns == 1
    assert r.correction_turns == 0, "a one-shot success is the perfect score"


def test_counts_and_weighting(tmp_path):
    p = _write(
        tmp_path,
        _user("build it"),
        _asst(),
        _user("go ahead"),
        _asst(),
        _user("no, use pytest instead"),
        _asst(),
        _user("also add rate limiting to the endpoint"),
    )
    r = analyze(p)
    assert r.correction_turns == 3
    assert r.counts == {"nudge": 1, "clarification": 0, "redirect": 1, "substantive": 1}
    assert r.weighted == 1.0 + 3.0 + 2.0


def test_nested_message_envelope(tmp_path):
    """Some transcript versions wrap the message; both shapes must work."""
    p = _write(
        tmp_path,
        {"message": {"role": "user", "content": "build it"}},
        {"message": {"role": "assistant", "content": "ok"}},
        {"message": {"role": "user", "content": "go ahead"}},
    )
    assert analyze(p).correction_turns == 1


def test_content_blocks(tmp_path):
    p = _write(
        tmp_path,
        {"role": "user", "content": [{"type": "text", "text": "build it"}]},
        _asst(),
        {"role": "user", "content": [{"type": "text", "text": "go ahead"}]},
    )
    assert analyze(p).correction_turns == 1


def test_malformed_lines_are_counted_not_fatal(tmp_path):
    """Transcript keys are untyped dict literals with no schema behind them."""
    p = tmp_path / "transcript.jsonl"
    p.write_text(
        '{"role":"user","content":"build it"}\n'
        "not json at all\n"
        "[1,2,3]\n"
        '{"role":"user","content":"go ahead"}\n',
        encoding="utf-8",
    )
    r = analyze(p)
    assert r.parse_errors == 2
    assert r.correction_turns == 1


def test_missing_file_is_not_fatal(tmp_path):
    r = analyze(tmp_path / "nope.jsonl")
    assert r.user_turns == 0 and r.correction_turns == 0
