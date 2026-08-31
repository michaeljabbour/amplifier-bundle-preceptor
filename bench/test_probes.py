"""Tests for the executable context probes.

THE LOAD-BEARING TESTS
-----------------------
Both regressions fixed alongside this file were probe-INSTRUMENT defects, not
context-content defects -- a broken measuring instrument silently producing a
confident wrong verdict, which is precisely the failure class this bundle
exists to detect, found in its own bench/ this time:

  1. `bench/probes/reduced/awareness.md` drifted out of sync with the shipped
     `context/awareness.md`, making `reduced` the LARGER file. That flips the
     sign of `saved = full_chars - reduced_chars` in probe_context.py, so an
     ADD would be handed to climb.decide() mislabeled as a REMOVE.
     test_reduced_fixture_is_synced_with_shipped_context pins the fixture;
     test_probe_context_rejects_a_stale_fixture proves probe_context.py now
     refuses to run rather than produce that inverted verdict.

  2. `must_not` for `stop-recording` was keyed to six leading verbs
     (set|edit|add|put|in|to), so any OTHER phrasing recommending the inert
     `settings.yaml` mechanism scored as correct. Reproduced 5 leaks out of 11
     tried phrasings. test_stop_recording_rejects_inert_mechanism replaces the
     previous 4-case self-test (which is how both leaks and a false-positive
     shipped in the first place) with the full matrix the fix was verified
     against: 14 cases total -- 5 that must PASS, 9 that must FAIL.

    uv run --no-project --with pytest --with pytest-asyncio --with pyyaml \
        pytest bench/test_probes.py -q
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).parent
PROBES = json.loads((HERE / "probes" / "context-probes.json").read_text())["probes"]

sys.path.insert(0, str(HERE))
from probe_context import reduction_is_live


def _probe(probe_id: str) -> dict:
    for p in PROBES:
        if p["id"] == probe_id:
            return p
    raise KeyError(probe_id)


def _scores(probe: dict, answer: str) -> bool:
    """Score exactly as probe_context.py:run_arm does: expect AND NOT must_not."""
    ok = bool(re.search(probe["expect"], answer))
    if ok and probe.get("must_not"):
        ok = not re.search(probe["must_not"], answer)
    return ok


# ---------------------------------------------------------------------------
# Every probe's regexes must at least compile. Cheap, and it is exactly the
# check that would have caught a typo before it reached a Digital Twin run.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("probe", PROBES, ids=[p["id"] for p in PROBES])
def test_probe_regexes_compile(probe: dict) -> None:
    re.compile(probe["expect"])
    if probe.get("must_not"):
        re.compile(probe["must_not"])


# ---------------------------------------------------------------------------
# stop-recording: the full PASS/FAIL matrix.
#
# 14 cases total: 3 working mechanisms + 2 correct denials must PASS (5), and
# 5 reproduced leaks + 2 already-correctly-rejected phrasings + 2 found by
# adversarial probing must FAIL (9). All 14 are asserted here -- undercounting
# a verification matrix is exactly the failure class this bundle exists to
# catch, so this file does not do it.
#
# On the last two: they were found by someone TRYING TO BREAK the rewritten
# regex, outside the 12 cases anyone had thought to write down. That is the
# point of committing them. The root cause of this whole defect was a
# self-test too small to contain the leaks -- and a matrix holding only the
# cases its author already imagined is that same failure wearing a larger
# number. Cases earned by attack belong in the file; add any future ones here.
# ---------------------------------------------------------------------------

STOP_RECORDING_MUST_PASS = [
    # working mechanisms
    "Compose `observe-only` (or unset `PRECEPTOR_ENABLED`) to stop recording.",
    "Run `preceptor off`.",
    "Unset PRECEPTOR_ENABLED=1 in your shell.",
    # correct denials that settings.yaml works -- the false positive the head
    # commit fixed. Must not regress.
    "There is no settings.yaml switch; compose observe-only instead.",
    "There is deliberately no `settings.yaml` switch — compose observe-only.",
]

STOP_RECORDING_MUST_FAIL = [
    # the 5 leaks Codex's PR #1 review reproduced against the shipped must_not
    "Configure settings.yaml with PRECEPTOR_ENABLED=0.",
    "Use settings.yaml; PRECEPTOR_ENABLED=0",
    "settings.yaml: PRECEPTOR_ENABLED=0",
    "Update your settings.yaml so PRECEPTOR_ENABLED is 0.",
    "Disable it via settings.yaml (PRECEPTOR_ENABLED=0).",
    # recommendations of the inert mechanism that were already correctly
    # rejected -- pinned so the rewrite does not regress them
    "Set `enabled: false` in settings.yaml.",
    "Add PRECEPTOR_ENABLED=0 to settings.yaml.",
    # found by adversarial probing AFTER the rewrite, outside the 12 cases
    # anyone had written down. A qualified path and an adverb between the verb
    # and the token -- both of which the old verb-anchored guard would have
    # been blind to.
    "Put PRECEPTOR_ENABLED=0 into ~/.amplifier/settings.yaml",
    "Simply edit settings.yaml and turn preceptor off.",
]


@pytest.mark.parametrize("answer", STOP_RECORDING_MUST_PASS)
def test_stop_recording_accepts_working_mechanisms(answer: str) -> None:
    assert _scores(_probe("stop-recording"), answer), answer


@pytest.mark.parametrize("answer", STOP_RECORDING_MUST_FAIL)
def test_stop_recording_rejects_inert_mechanism(answer: str) -> None:
    assert not _scores(_probe("stop-recording"), answer), answer


# ---------------------------------------------------------------------------
# KNOWN, ACCEPTED LIMITATION -- do not "fix" this by loosening the regex.
# ---------------------------------------------------------------------------

# A correct denial phrased with the negation NOT adjacent to the token. The
# lookbehinds only cover `no `/`not ` immediately preceding `settings.yaml`,
# so this scores FAIL.
KNOWN_FALSE_FAIL = "The observe-only bundle is the way; settings.yaml does nothing."


@pytest.mark.xfail(
    strict=True,
    reason="accepted false FAIL: non-adjacent negation. Loosening toward "
    "denial-tolerance re-opens the false-PASS direction, which is the "
    "dangerous one. See the docstring before changing must_not.",
)
def test_denial_with_non_adjacent_negation_is_an_accepted_false_fail() -> None:
    """Records a miss this instrument takes DELIBERATELY.

    1. THE INSTRUMENT IS WRONG HERE. `KNOWN_FALSE_FAIL` is a correct answer --
       it names a working mechanism and correctly denies that settings.yaml
       does anything -- and the probe scores it FAIL. The negation
       lookbehinds match only `no `/`not ` directly before the token, and here
       the denial ("does nothing") trails it. So this test asserts the answer
       SHOULD score PASS and is marked xfail because it does not.

    2. THE MISS DIRECTION IS THE SAFE ONE, AND THAT IS THE WHOLE POINT. This
       probe gates every downstream context-removal experiment. A false FAIL
       costs tokens that might not have been needed -- recoverable, and it
       fails toward keeping context. A false PASS blesses the settings.yaml
       mechanism that was PROVEN INERT in a Digital Twin (zero records, exit
       0, no error), scoring a candidate as preserving the consent control
       while it actually breaks it, and corrupts every experiment this probe
       grades. The two errors are not symmetric and must not be traded off as
       if they were. Any rewrite that tolerates denials in general also
       admits recommendations -- Codex's PR #1 review reproduced 5 such leaks
       against the previous verb-enumerated guard. Widen this and you re-open
       exactly that hole.

    3. IT IS UNREACHABLE IN PRACTICE. The denial sentence was removed from
       `context/awareness.md`, so the model has no prompt to emit any denial
       at all. The verified DTU run after that removal was 5/5 with no
       settings.yaml mention in any of the five answers.

    strict=True is deliberate: if someone loosens `must_not` this turns XPASS
    and fails the suite, which routes them here to read points 2 and 3 first.
    """
    assert _scores(_probe("stop-recording"), KNOWN_FALSE_FAIL)


# ---------------------------------------------------------------------------
# Defect 1's guard: probe_context.py must refuse to run, not silently invert,
# when there is no live reduction candidate (reduced >= full).
# ---------------------------------------------------------------------------


def test_reduced_fixture_is_synced_with_shipped_context() -> None:
    """The fixture drifting out of sync is exactly what inverted the ablation
    once already. Pin it so it cannot happen silently again."""
    shipped = (HERE.parent / "context" / "awareness.md").read_text()
    fixture = (HERE / "probes" / "reduced" / "awareness.md").read_text()
    assert shipped == fixture


@pytest.mark.parametrize(
    ("full_chars", "reduced_chars"),
    [(100, 100), (100, 150)],
    ids=["equal", "reduced-larger"],
)
def test_reduction_is_live_rejects_non_reductions(
    full_chars: int, reduced_chars: int
) -> None:
    msg = reduction_is_live(full_chars, reduced_chars)
    assert msg is not None
    assert "no live reduction candidate" in msg


def test_reduction_is_live_accepts_a_real_reduction() -> None:
    assert reduction_is_live(100, 50) is None


def test_probe_context_aborts_when_no_reduction_candidate_is_live() -> None:
    """End-to-end: with the fixture synced (reduced == full), running the
    script for real must exit non-zero before ever touching a Digital Twin."""
    result = subprocess.run(
        [sys.executable, str(HERE / "probe_context.py"), "--container", "unused"],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode != 0
    assert "no live reduction candidate" in result.stderr.lower()
