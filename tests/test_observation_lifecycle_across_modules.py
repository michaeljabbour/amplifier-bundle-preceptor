"""CROSS-MODULE: a record the OBSERVER writes must be deletable by the TOOL.

WHY THIS FILE IS AT THE REPO ROOT, next to test_project_slug_agreement.py
--------------------------------------------------------------------------
Same reason, and the same shape of defect. `hooks-trajectory-observer` WRITES
observation records; `tool-preceptor` READS and DELETES them. Each module's
own suite is green. Neither can see the seam between them, and both defects
found in that seam were invisible to every in-module test:

  1. The two modules resolved `{project}` differently, so the tool read a
     directory the observer never wrote to (see
     tests/test_project_slug_agreement.py).

  2. The two modules disagreed about TIMESTAMPS. The observer writes
     `datetime.now(timezone.utc).isoformat()` -- always timezone-AWARE. The
     tool's `_parse_timestamp` stripped a trailing `Z` but never localised a
     naive parse, so a bare `2026-08-01` came back NAIVE and Python refuses
     to compare the two:

         TypeError: can't compare offset-naive and offset-aware datetimes

     The bare date is the form `docs/CONSENT.md` DOCUMENTS
     (`preceptor forget --since <date>`), so the documented control failed on
     the documented invocation. Live, two of two natural asks hit it; it only
     appeared to work because the model retried unprompted with `+00:00`.

`modules/tool-preceptor/tests/test_ledger.py` now covers the `since`-form
matrix using hand-written timestamp strings. This file covers the part that
matrix cannot: that the format the observer ACTUALLY produces, from the
observer's own code, is deletable. If the observer ever changes its
timestamp format, the in-module tests all stay green and this one fails --
which is the entire point.

    uv run --no-project --with pytest --with pyyaml --with amplifier-core \
        pytest tests/ -q
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]

for _module_dir in (
    "hooks-trajectory-observer",
    "hooks-cue-injector",
    "tool-preceptor",
):
    sys.path.insert(0, str(_REPO_ROOT / "modules" / _module_dir))

import amplifier_module_hooks_cue_injector as injector
import amplifier_module_hooks_trajectory_observer as observer
from amplifier_module_tool_preceptor import ledger


def _observer_timestamp() -> str:
    """The observer's OWN timestamp, from the observer's own function.

    Deliberately calls `observer._now_iso()` rather than reproducing its
    format here. A hand-copied format string would keep passing after the
    observer changed, which is exactly the failure mode this file exists to
    catch.
    """
    return observer._now_iso()


def _write_record_as_the_observer_would(
    root: Path, obs_id: str, ts: str, session: str = "sess-cross-module"
) -> None:
    """One JSONL line in the observer's record shape, in the observer's
    directory layout."""
    obs_dir = root / "observations"
    obs_dir.mkdir(parents=True, exist_ok=True)
    record: dict[str, Any] = {
        "v": 1,
        "id": obs_id,
        "ts": ts,
        "session": session,
        "event": "tool:post",
        "tool_name": "edit_file",
        "ok": True,
    }
    with open(obs_dir / f"{session}.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(record, sort_keys=False) + "\n")


def test_the_observers_timestamp_format_is_timezone_aware() -> None:
    """The premise of everything below, asserted rather than assumed."""
    parsed = datetime.fromisoformat(_observer_timestamp())
    assert parsed.tzinfo is not None, (
        "the observer no longer writes an aware timestamp; the tool's "
        "localisation assumption needs rechecking"
    )


def test_the_injector_stamps_manifests_with_an_aware_timestamp() -> None:
    """The third module's timestamps, pinned before they become a defect.

    The injector writes `"ts": datetime.now(timezone.utc).isoformat()` into
    each per-session dosing manifest. NOTHING COMPARES MANIFEST TIMESTAMPS
    TODAY, so this is a forward guard rather than a live invariant -- if
    something ever does compare them, the third module should already be
    known to agree instead of becoming the next seam defect.

    KNOWN WEAKNESS, STATED RATHER THAN IMPLIED. This is a SOURCE-LEVEL
    assertion -- it greps the injector's own file for the construction --
    and it is strictly weaker than the behavioural tests around it. It would
    not catch a change that kept the literal text while altering what
    actually gets written. The injector builds that timestamp inline while
    writing a manifest rather than in a callable helper, so exercising it
    behaviourally would mean standing up a full dosing path for a property
    nothing currently reads. That trade is the reason for the weaker form;
    it is not an oversight.

    THIS DOCSTRING IS ALSO THE RECORD OF A DEFECT IN THIS TEST. Its first
    draft asserted:

        assert "timezone" in injector.__dict__ or True

    which is a tautology -- the `or True` makes it unfailable, so it would
    have reported success forever regardless of what the injector did. That
    is the same vacuous-assertion class this branch had just spent a round
    removing from `bench/test_probes.py`'s subsystem audit, reintroduced by
    the same author in a brand-new file one commit later. It was caught by a
    linter, not by review.

    The lesson worth keeping: an honest weaker test, labelled as weak, beats
    a strong-looking one that cannot fail. If you replace this with
    something stronger, good -- but do not replace it with something that
    merely looks stronger.
    """
    injector_file = injector.__file__
    assert injector_file is not None, "injector module has no __file__"
    source = Path(injector_file).read_text(encoding="utf-8")
    assert "datetime.now(timezone.utc).isoformat()" in source, (
        "the injector no longer stamps manifests with an aware UTC "
        "timestamp; if manifest timestamps ever get compared, re-check "
        "_parse_timestamp's localisation assumption"
    )


def test_forget_with_a_bare_date_deletes_a_record_the_observer_wrote(
    tmp_path: Path,
) -> None:
    """THE LOAD-BEARING TEST -- the exact live failure, end to end.

    Observer-format timestamp in, documented bare-date `since` in, record
    gone out. Before the fix this raised TypeError before deleting anything.
    """
    root = tmp_path / "preceptor"
    _write_record_as_the_observer_would(root, "obs-1", _observer_timestamp())

    yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")
    result = ledger.forget(root, yesterday)

    assert result["deleted_observations"] == 1
    assert not (root / "observations" / "sess-cross-module.jsonl").exists()


def test_every_since_form_deletes_the_observers_own_records_identically(
    tmp_path: Path,
) -> None:
    """The `since`-form matrix, run against records the observer actually
    produced rather than against hand-written timestamp strings.

    Asserts on DELETED COUNTS, not on absence of an exception: a version
    that parsed every form to the same wrong instant and deleted nothing
    would pass a does-not-raise test while failing the user completely.
    """
    now = datetime.now(timezone.utc)
    yesterday = (now - timedelta(days=1)).strftime("%Y-%m-%d")

    since_forms = [
        yesterday,  # THE DOCUMENTED FORM -- this is what crashed
        f"{yesterday}T00:00:00",  # naive datetime
        f"{yesterday}T00:00:00Z",  # what the model retried with
        f"{yesterday}T00:00:00+00:00",  # explicit UTC
        f"{yesterday}T00:00:00-05:00",  # non-UTC offset, still before `now`
    ]

    counts: dict[str, int] = {}
    for since in since_forms:
        root = tmp_path / f"preceptor-{since.replace(':', '').replace('+', 'p')}"
        # Three recent records (all after every boundary above) and one old
        # one that must survive, so "deleted everything" cannot pass as
        # "deleted the right thing".
        for i in range(3):
            _write_record_as_the_observer_would(
                root, f"obs-recent-{i}", _observer_timestamp()
            )
        old = (now - timedelta(days=400)).isoformat()
        _write_record_as_the_observer_would(root, "obs-old", old)

        counts[since] = ledger.forget(root, since)["deleted_observations"]

        surviving = [
            json.loads(line)
            for line in (root / "observations" / "sess-cross-module.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()
            if line.strip()
        ]
        assert [r["id"] for r in surviving] == ["obs-old"], (
            f"since={since!r} did not preserve the pre-boundary record"
        )

    assert set(counts.values()) == {3}, (
        "every equivalent `since` form must delete the same three records; got "
        + ", ".join(f"{k!r}->{v}" for k, v in counts.items())
    )


def test_records_written_under_the_resolved_root_are_the_ones_forget_deletes(
    tmp_path: Path,
) -> None:
    """Ties the two seam defects together.

    The slug fix made the tool READ the directory the observer WRITES; the
    timestamp fix made it able to DELETE what it finds there. Either one
    alone still leaves `forget` reporting success while doing nothing, which
    is how both defects presented. This asserts the whole path with a single
    root resolved the way both modules now resolve it.
    """

    class _Coordinator:
        def get_capability(self, name: str) -> Any:
            return (
                str(tmp_path / "workspace") if name == "session.working_dir" else None
            )

    coordinator = _Coordinator()
    template = "{project}/preceptor"

    observer_slug = observer._project_slug(coordinator)
    tool_slug = ledger.resolve_root("{project}", observer_slug)

    assert observer_slug == injector._project_slug(coordinator)

    root = tmp_path / "roots" / template.format(project=observer_slug)
    assert observer_slug in str(tool_slug)

    _write_record_as_the_observer_would(root, "obs-1", _observer_timestamp())
    yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")

    assert ledger.forget(root, yesterday)["deleted_observations"] == 1


if __name__ == "__main__":  # pragma: no cover
    pytest.main([__file__])
