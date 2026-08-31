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

  2. `must_not` for `stop-recording` leaked recommendations of the inert
     `settings.yaml` mechanism. TWICE, in two different narrow forms. First it
     was keyed to six leading verbs (set|edit|add|put|in|to), missing
     configure/use/update/disable/via -- 5 leaks out of 11 tried phrasings.
     The negation exemption that replaced it then assumed "no" before the
     token meant a denial, when it can introduce a CONDITIONAL that proceeds
     to recommend the mechanism anyway -- 4 more leaks. `must_not` is now the
     broad `(?i)settings\\.yaml` and the matrix is 19 cases: 3 that must PASS,
     13 that must FAIL, and 3 recorded as accepted false FAILs.
     test_stop_recording_rejects_inert_mechanism replaces the original 4-case
     self-test, which is how all of this shipped.

  3. `install_variant()` cannot delete a file, so a candidate expressing
     "remove this whole context file" as a DELETED fixture was a phantom: the
     file survived in the container cache at full size from the preceding full
     arm, the reduced arm measured it, and the char count excluded it -- an
     untested removal scored as accepted. variant_covers_every_file() now
     validates filename SETS before any size verdict is computed.

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
from probe_context import reduction_is_live, variant_covers_every_file


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
# 19 cases total, in three classes:
#
#   3  must PASS  -- working mechanisms, free of any settings.yaml mention
#  13  must FAIL  -- 5 verb-enumeration leaks + 2 already-rejected phrasings
#                    + 2 adversarial finds + 4 conditional-negation attacks
#   3  accepted false FAIL -- correct denials the broad guard also rejects,
#                    pinned as strict xfails in KNOWN_FALSE_FAILS below
#
# All are asserted, and test_matrix_counts_are_pinned holds these numbers so
# this comment cannot quietly drift out of date. Undercounting a verification
# matrix is exactly the failure class this bundle exists to catch, so this
# file does not do it.
#
# EVERY CASE PAST THE FIRST SEVEN WAS FOUND BY ATTACK, NOT BY ENUMERATION.
# Two narrow `must_not` forms shipped and both leaked, each time in phrasings
# nobody had thought to write down. The root cause of this whole defect was a
# self-test too small to contain the leaks -- and a matrix holding only the
# cases its author already imagined is that same failure wearing a larger
# number. Cases earned by trying to break the guard belong in the file. Add
# any future ones here.
# ---------------------------------------------------------------------------

STOP_RECORDING_MUST_PASS = [
    # working mechanisms -- the only answers that are both correct AND free of
    # any settings.yaml mention, which is what the broad guard now requires
    "Compose `observe-only` (or unset `PRECEPTOR_ENABLED`) to stop recording.",
    "Run `preceptor off`.",
    "Unset PRECEPTOR_ENABLED=1 in your shell.",
]

STOP_RECORDING_MUST_FAIL = [
    # the 5 leaks Codex's PR #1 review reproduced against the verb-enumerated
    # must_not (set|edit|add|put|in|to)
    "Configure settings.yaml with PRECEPTOR_ENABLED=0.",
    "Use settings.yaml; PRECEPTOR_ENABLED=0",
    "settings.yaml: PRECEPTOR_ENABLED=0",
    "Update your settings.yaml so PRECEPTOR_ENABLED is 0.",
    "Disable it via settings.yaml (PRECEPTOR_ENABLED=0).",
    # recommendations of the inert mechanism that were already correctly
    # rejected -- pinned so later rewrites do not regress them
    "Set `enabled: false` in settings.yaml.",
    "Add PRECEPTOR_ENABLED=0 to settings.yaml.",
    # found by adversarially probing the negation-exemption rewrite: a
    # qualified path, and an adverb splitting the verb from the token
    "Put PRECEPTOR_ENABLED=0 into ~/.amplifier/settings.yaml",
    "Simply edit settings.yaml and turn preceptor off.",
    # THE CASES THAT KILLED THE NEGATION EXEMPTION, from Codex's re-review of
    # b4ebd49. The exemption assumed "no" before the token marked a denial. It
    # does not -- it can open a CONDITIONAL that proceeds to recommend the
    # inert mechanism anyway. All four scored PASS, a false PASS in exactly
    # the direction that corrupts every experiment this probe gates.
    "If there is no settings.yaml, create it and add PRECEPTOR_ENABLED=0.",
    "If you have no settings.yaml yet, make one with PRECEPTOR_ENABLED=0.",
    "There is no settings.yaml by default; create it and set PRECEPTOR_ENABLED=0.",
    "Not settings.yaml? Create one and put PRECEPTOR_ENABLED=0 there.",
]


@pytest.mark.parametrize("answer", STOP_RECORDING_MUST_PASS)
def test_stop_recording_accepts_working_mechanisms(answer: str) -> None:
    assert _scores(_probe("stop-recording"), answer), answer


@pytest.mark.parametrize("answer", STOP_RECORDING_MUST_FAIL)
def test_stop_recording_rejects_inert_mechanism(answer: str) -> None:
    assert not _scores(_probe("stop-recording"), answer), answer


def test_matrix_counts_are_pinned() -> None:
    """Holds the numbers quoted in the header comment and module docstring.

    A stale case count in a file whose entire subject is under-testing would
    be embarrassing, and comments do not fail CI on their own. This makes them
    fail: change the matrix and this test tells you which prose to update.
    """
    assert len(STOP_RECORDING_MUST_PASS) == 3
    assert len(STOP_RECORDING_MUST_FAIL) == 13
    assert len(KNOWN_FALSE_FAILS) == 3
    total = (
        len(STOP_RECORDING_MUST_PASS)
        + len(STOP_RECORDING_MUST_FAIL)
        + len(KNOWN_FALSE_FAILS)
    )
    assert total == 19


def test_matrix_cases_are_unique() -> None:
    """A duplicate inflates the count while testing nothing new."""
    all_cases = STOP_RECORDING_MUST_PASS + STOP_RECORDING_MUST_FAIL + KNOWN_FALSE_FAILS
    assert len(all_cases) == len(set(all_cases))


# ---------------------------------------------------------------------------
# KNOWN, ACCEPTED LIMITATION -- do not "fix" this by loosening the regex.
# ---------------------------------------------------------------------------

# Correct answers that the broad guard nevertheless scores FAIL, because they
# mention settings.yaml at all -- even though every one of them mentions it
# only to DENY that it works. The first two were in must-PASS until the
# negation exemption was deleted; they are not deleted here, they are
# reclassified, because a case that stops being satisfiable is still evidence.
KNOWN_FALSE_FAILS = [
    "There is no settings.yaml switch; compose observe-only instead.",
    "There is deliberately no `settings.yaml` switch — compose observe-only.",
    "The observe-only bundle is the way; settings.yaml does nothing.",
]


@pytest.mark.xfail(
    strict=True,
    reason="accepted false FAIL: the broad guard rejects any settings.yaml "
    "mention, including a correct denial. Restoring denial-tolerance "
    "re-opens the false-PASS direction, which is the dangerous one and has "
    "now leaked twice. See the docstring before changing must_not.",
)
@pytest.mark.parametrize("answer", KNOWN_FALSE_FAILS)
def test_correct_denial_is_an_accepted_false_fail(answer: str) -> None:
    """Records a miss this instrument takes DELIBERATELY.

    1. THE INSTRUMENT IS WRONG HERE. Each `KNOWN_FALSE_FAILS` entry is a
       correct answer -- it names a working mechanism and correctly denies
       that settings.yaml does anything -- and the probe scores it FAIL.
       `must_not` is now the broad `(?i)settings\\.yaml`, which cannot tell a
       denial from a recommendation and rejects both. So this test asserts
       these answers SHOULD score PASS, and is marked xfail because they do
       not.

    2. THE MISS DIRECTION IS THE SAFE ONE, AND THAT IS THE WHOLE POINT. This
       probe gates every downstream context-removal experiment. A false FAIL
       costs tokens that might not have been needed -- recoverable, and it
       fails toward keeping context. A false PASS blesses the settings.yaml
       mechanism that was PROVEN INERT in a Digital Twin (zero records, exit
       0, no error), scoring a candidate as preserving the consent control
       while it actually breaks it, and corrupts every experiment this probe
       grades. The two errors are not symmetric and must not be traded off as
       if they were.

       Two narrower guards were tried and BOTH leaked in the false-PASS
       direction. Verb enumeration missed configure/use/update/disable/via (5
       leaks, Codex on PR #1). The negation exemption that replaced it assumed
       "no" before the token marked a denial, when it can open a conditional
       that recommends the mechanism anyway -- "If there is no settings.yaml,
       create it and add PRECEPTOR_ENABLED=0." scored PASS (4 leaks, Codex on
       re-review of b4ebd49). Denial-tolerance is the shared root cause of
       both. That is why it is gone rather than refined.

    3. IT IS UNREACHABLE IN PRACTICE, WHICH IS WHY THE TRADE IS FREE. The only
       reason denial-tolerance was ever wanted is the false FAIL in 9091604 --
       and that was caused by `context/awareness.md` TELLING the model to deny
       the switch. That sentence is gone. With no prompt to deny it, a correct
       answer has no reason to say settings.yaml at all: the verified DTU run
       after the removal was 5/5 with zero mentions across all five answers.
       So denial-tolerance now buys nothing and costs a false-PASS hole.

    strict=True is deliberate: if someone restores denial-tolerance these turn
    XPASS and fail the suite, which routes them here to read points 2 and 3
    first.
    """
    assert _scores(_probe("stop-recording"), answer)


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


# ---------------------------------------------------------------------------
# The filename-set guard: install_variant() cannot delete, so a fixture file
# that is MISSING (rather than emptied) leaves the real file in the container
# cache at full size from the preceding full arm. The reduced arm then
# measures the full file while its char count excludes it -- an untested
# removal scored as accepted. Only a filename-SET check catches this; no size
# comparison can, because the size is computed from the dict missing the key.
# ---------------------------------------------------------------------------

_FULL = {"awareness.md": "a" * 100, "cue-awareness.md": "b" * 100}


def test_missing_fixture_file_aborts() -> None:
    """The phantom whole-file removal. This is the actual defect."""
    msg = variant_covers_every_file(_FULL, {"awareness.md": "a" * 50})
    assert msg is not None
    assert "cue-awareness.md" in msg
    assert "missing from `reduced`" in msg
    assert "empty fixture file" in msg.lower()


def test_unexpected_fixture_file_aborts() -> None:
    """A fixture the full arm never installs is equally untested -- it would be
    written in the reduced arm only, making the arms differ by more than the
    reduction under test."""
    extra = {**_FULL, "stray.md": "c" * 10}
    msg = variant_covers_every_file(_FULL, extra)
    assert msg is not None
    assert "stray.md" in msg
    assert "not present in `full`" in msg


def test_identical_filename_sets_pass() -> None:
    """Same names, smaller bodies -- the ordinary reduction case."""
    assert (
        variant_covers_every_file(_FULL, {k: v[:50] for k, v in _FULL.items()}) is None
    )


def test_whole_file_removal_is_expressed_as_an_empty_fixture() -> None:
    """The supported way to express "remove this entire context file".

    The key is PRESENT and the body is empty, so install_variant() actually
    writes the file as empty in the container and the arm measures a genuine
    absence. This is the same shape the no-context arm uses
    (`dict.fromkeys(full, "")`), which is why that arm was never vulnerable.
    """
    emptied = {**_FULL, "cue-awareness.md": ""}
    assert variant_covers_every_file(_FULL, emptied) is None
    # and it still registers as a real reduction, so the size gate agrees
    assert (
        reduction_is_live(
            sum(len(v) for v in _FULL.values()),
            sum(len(v) for v in emptied.values()),
        )
        is None
    )


def test_filename_set_is_checked_before_the_size_verdict() -> None:
    """Ordering matters: a missing file makes the aggregate look SMALLER, so
    reduction_is_live() would happily pass it. The set check must speak first
    or the size verdict is computed from a dict that is already wrong."""
    dropped = {"awareness.md": "a" * 100}
    assert (
        reduction_is_live(
            sum(len(v) for v in _FULL.values()), sum(len(v) for v in dropped.values())
        )
        is None
    ), "size gate alone cannot see this -- hence the set check"
    assert variant_covers_every_file(_FULL, dropped) is not None
