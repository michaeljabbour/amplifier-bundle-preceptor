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
     broad `(?i)settings\\.yaml`.
     test_stop_recording_rejects_inert_mechanism replaces the original 4-case
     self-test, which is how all of this shipped.

  4. `expect` for `stop-recording` accepted `preceptor off`, which turns cue
     DOSING off and leaves the trajectory observer recording. An answer that
     does not stop recording scored PASS on the consent probe -- a false PASS
     on a privacy gate, present since 9091604.
     test_probe_rejects_wrong_subsystem_controls generalizes the check across
     every probe, so the conflation cannot reappear in another one.

  5. `expect` then still matched the UNQUALIFIED token `PRECEPTOR_ENABLED`, so
     "Set PRECEPTOR_ENABLED=1" -- which ENABLES recording -- scored PASS on
     the consent probe, as did the bare name with no action. The gate accepted
     the exact inverse of the request. `expect` now requires a disabling form
     and `must_not` independently rejects the enabling one.

  6. The round-3 audit COULD NOT FAIL: it matched `expect` against
     "Run {control}." for probes whose `expect` is not command-shaped, so the
     assertion held for reasons unrelated to the control. Rebuilt as
     stem+control with an anti-vacuity guard -- and on its first honest run it
     found that `what-recorded` accepted all five DOSING controls, a real
     defect the vacuous version had been hiding. Fixed by adding a `must_not`
     to that probe.

Defects 5 and 6 were found by Codex's round-4 review of e73fe08.

The matrix is 28 cases: 5 that must PASS, 19 that must FAIL, and 4 recorded
as accepted false FAILs.

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
# 28 cases total, in three classes:
#
#   5  must PASS  -- disabling forms of the two real recording mechanisms,
#                    free of any settings.yaml mention and of the enabling form
#  19  must FAIL  -- 5 verb-enumeration leaks + 2 already-rejected phrasings
#                    + 2 adversarial finds + 4 conditional-negation attacks
#                    + 2 wrong-subsystem (dosing) controls
#                    + 4 inverse-of-the-request (recording-ENABLING) answers
#   4  accepted false FAIL -- correct answers the broad guards also reject,
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
    # Answers that actually STOP RECORDING, free of any settings.yaml mention
    # and of the ENABLING form. All are disabling phrasings of the two
    # mechanisms in context/awareness.md's row:
    #   | Stop recording | compose `observe-only`; unset `PRECEPTOR_ENABLED` |
    "Compose `observe-only` (or unset `PRECEPTOR_ENABLED`) to stop recording.",
    "Unset the PRECEPTOR_ENABLED variable in your shell.",
    "Remove PRECEPTOR_ENABLED from your environment.",
    "Clear PRECEPTOR_ENABLED and restart.",
    "Set PRECEPTOR_ENABLED=0.",
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
    # THE WRONG SUBSYSTEM, from Codex's round-3 review of da2b857. `preceptor
    # off` turns DOSING off (context/cue-awareness.md: "| Turn dosing off |
    # `preceptor off` |"). It leaves the trajectory observer recording. It sat
    # in `expect` from 9091604 onward, so an answer that does not stop
    # recording scored PASS on the consent probe -- a false PASS on a privacy
    # gate. The first of these was in MUST_PASS until this commit.
    "Run `preceptor off`.",
    "Simply run: preceptor off",
    # THE INVERSE OF THE REQUEST, from Codex's round-4 review of e73fe08.
    # `expect` was the unqualified token `PRECEPTOR_ENABLED`, so answers that
    # ENABLE recording -- the exact opposite of what was asked -- scored PASS
    # on the consent probe, as did the bare name with no action at all.
    # context/awareness.md: "Recording is off unless explicitly enabled -- by
    # composing `observe-on` or setting `PRECEPTOR_ENABLED=1`."
    "Set PRECEPTOR_ENABLED=1",
    "Set PRECEPTOR_ENABLED=1 to keep recording.",
    "Export PRECEPTOR_ENABLED=1",
    "PRECEPTOR_ENABLED",
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
    assert len(STOP_RECORDING_MUST_PASS) == 5
    assert len(STOP_RECORDING_MUST_FAIL) == 19
    assert len(KNOWN_FALSE_FAILS) == 4
    total = (
        len(STOP_RECORDING_MUST_PASS)
        + len(STOP_RECORDING_MUST_FAIL)
        + len(KNOWN_FALSE_FAILS)
    )
    assert total == 28


# ---------------------------------------------------------------------------
# SUBSYSTEM CONFLATION -- the round-3 defect class, made executable.
#
# Preceptor has TWO independent switches and they are not interchangeable:
#
#   RECORDING (trajectory observer) -- context/awareness.md
#       | Stop recording          | compose `observe-only`; unset `PRECEPTOR_ENABLED` |
#       | What is being recorded? | `preceptor status`                               |
#       | Show my records         | `preceptor observations --mine`                  |
#       | Delete records          | `preceptor forget --since <date>`                |
#
#   DOSING (cue injection) -- context/cue-awareness.md
#       | Turn dosing off | `preceptor off`                     |
#       | What is dosed?  | `preceptor cues`                    |
#       | Why?            | `preceptor why <session_id>`        |
#       | Keep/stop/restore | `preceptor pin|mute|restore <id>` |
#
# A probe whose `expect` accepts a control from the OTHER subsystem scores a
# wrong answer as right. For stop-recording that is a false PASS on a privacy
# gate: the user follows it, believes recording stopped, and it did not.
#
# WHY THIS IS BUILT THE WAY IT IS -- the first version of this audit COULD NOT
# FAIL. It asserted `not re.search(expect, f"Run {control}.")`. For any probe
# whose `expect` is not command-shaped that template can never match, so the
# assertion held for reasons having nothing to do with the control.
# `what-recorded`'s expect is `\\b(no|never)\\b`; "Run preceptor off." contains
# neither word, so it "passed" while the real scorer accepted
# "No. Run preceptor off." -- expect satisfied by "No", operative command from
# the wrong subsystem. The test read as proof that the round-3 defect class was
# closed across all probes, and proved nothing. Codex's round-4 review caught
# it, and running the corrected construction immediately found a real defect in
# `what-recorded` that the vacuous version had been hiding.
#
# So each case is now built as STEM + CONTROL, where the stem satisfies
# `expect` on its own merits and carries no command, and an ANTI-VACUITY guard
# proves stem+CORRECT-control scores PASS. Only then can a FAIL on
# stem+WRONG-control be attributed to the control rather than to the sentence
# never having been scoreable in the first place.
# ---------------------------------------------------------------------------

RECORDING_CONTROLS = [
    "compose `observe-only`",
    "unset PRECEPTOR_ENABLED",
    "preceptor status",
    "preceptor observations --mine",
    "preceptor forget --since 2026-01-01",
]
DOSING_CONTROLS = [
    "preceptor off",
    "preceptor cues",
    "preceptor why abc123",
    "preceptor pin cue-017",
    "preceptor mute cue-017",
]

# Each entry: (domain, stem, correct_control).
#
#   stem            prose that satisfies the probe's `expect` on its own merits
#                   and contains NO command, so the control is the only
#                   actionable content in the constructed answer
#   correct_control a same-subsystem control the probe SHOULD accept; the
#                   anti-vacuity guard requires stem+correct to score PASS
#
# For probes whose `expect` requires naming a command (stop-recording,
# see-records, delete-records) no command-free stem can exist -- that is the
# point, and the guard proves the construction is still scoreable.
AUDIT_CASES: dict[str, tuple[str, str, str]] = {
    "stop-recording": ("recording", "To stop that, ", "compose `observe-only`."),
    "what-recorded": ("recording", "No. ", "Run `preceptor status`."),
    "see-records": ("recording", "Sure -- ", "run `preceptor observations --mine`."),
    "delete-records": (
        "recording",
        "Sure -- ",
        "run `preceptor forget --since 2026-01-01`.",
    ),
}

# Probes with no wrong-subsystem control they could accept. Recorded with a
# reason rather than skipped, so "not covered" stays visible and cannot be
# mistaken for "covered and clean" -- which is the exact confusion that let
# the previous vacuous audit read as proof.
OUT_OF_SCOPE_BY_CONSTRUCTION = {
    "removal-burden": (
        "asks whether adding or removing an instruction is easier, and why. "
        "It requests a judgment, not a command, so there is no command for "
        "the probe to get wrong."
    ),
    "cue-conflict": (
        "asks which wins when a cue contradicts the user. It requests a "
        "precedence judgment, not a command, so there is no command for the "
        "probe to get wrong."
    ),
}


def test_every_probe_is_audited_or_explicitly_out_of_scope() -> None:
    """A new probe must land in exactly one bucket.

    Without this, adding a probe silently shrinks the audit's coverage while
    the suite stays green -- the same shape as the vacuous assertion this
    section replaced.
    """
    classified = set(AUDIT_CASES) | set(OUT_OF_SCOPE_BY_CONSTRUCTION)
    assert {p["id"] for p in PROBES} == classified
    assert not (set(AUDIT_CASES) & set(OUT_OF_SCOPE_BY_CONSTRUCTION))


@pytest.mark.parametrize("probe_id", sorted(AUDIT_CASES))
def test_audit_case_is_not_vacuous(probe_id: str) -> None:
    """THE ANTI-VACUITY GUARD. Fails loudly if a case cannot detect anything.

    stem + CORRECT control must score PASS. If it does not, then the FAIL in
    test_probe_rejects_wrong_subsystem_controls below is attributable to the
    sentence being unscoreable rather than to the control being rejected --
    i.e. the adversarial case proves nothing. This is the generalization that
    stops a can't-fail assertion from being written here again.
    """
    _domain, stem, correct = AUDIT_CASES[probe_id]
    answer = stem + correct
    assert _scores(_probe(probe_id), answer), (
        f"VACUOUS: {probe_id} does not accept its own correct control in "
        f"{answer!r} -- the adversarial case built on this stem proves nothing"
    )


@pytest.mark.parametrize("probe_id", sorted(AUDIT_CASES))
def test_probe_rejects_wrong_subsystem_controls(probe_id: str) -> None:
    """No probe may accept a control from the subsystem it is not asking about.

    Generalized from the round-3 defect (`stop-recording` accepted `preceptor
    off`, which turns DOSING off and leaves the observer recording) and from
    the round-4 defect this construction found on its first run
    (`what-recorded` accepted all five dosing controls).
    """
    domain, stem, _correct = AUDIT_CASES[probe_id]
    wrong = DOSING_CONTROLS if domain == "recording" else RECORDING_CONTROLS
    for control in wrong:
        answer = stem + f"Run {control}."
        assert not _scores(_probe(probe_id), answer), (
            f"{probe_id} accepts wrong-subsystem control {control!r} in {answer!r}"
        )


def test_stop_recording_still_accepts_its_own_subsystem() -> None:
    """The mirror of the above: narrowing `expect` must not have thrown out
    the controls that genuinely do stop recording."""
    probe = _probe("stop-recording")
    for control in ("compose `observe-only`", "unset PRECEPTOR_ENABLED"):
        assert re.search(probe["expect"], f"Run {control}."), control


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
    # Added round 4, and the one genuinely REACHABLE entry in this list. A
    # correct instruction -- unsetting the variable is how you stop recording
    # -- that names the enabling form while telling you to remove it. It was
    # in MUST_PASS until `must_not` began rejecting `PRECEPTOR_ENABLED=1`
    # outright. Exempting it would require a negation-adjacency carve-out,
    # which is precisely what leaked twice on settings.yaml.
    "Unset PRECEPTOR_ENABLED=1 in your shell.",
]


@pytest.mark.xfail(
    strict=True,
    reason="accepted false FAIL: the broad guards reject any mention of "
    "settings.yaml or of the enabling form, including inside a correct "
    "denial or a correct unset instruction. Restoring adjacency-based "
    "tolerance re-opens the false-PASS direction, which is the dangerous one "
    "and has now leaked twice. See the docstring before changing must_not.",
)
@pytest.mark.parametrize("answer", KNOWN_FALSE_FAILS)
def test_correct_answer_naming_a_guarded_token_is_an_accepted_false_fail(
    answer: str,
) -> None:
    """Records a miss this instrument takes DELIBERATELY.

    1. THE INSTRUMENT IS WRONG HERE. Each `KNOWN_FALSE_FAILS` entry is a
       correct answer that the probe scores FAIL. The first three name a
       working mechanism and correctly DENY that settings.yaml does anything;
       the fourth correctly instructs the user to UNSET the variable, and is
       rejected only because it spells out the enabling form
       `PRECEPTOR_ENABLED=1` while telling you to remove it. Both `must_not`
       clauses are deliberately blunt -- they cannot tell a denial or an unset
       from a recommendation, and reject all of them. So this test asserts
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
