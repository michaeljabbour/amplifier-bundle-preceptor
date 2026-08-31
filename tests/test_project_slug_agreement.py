"""CROSS-MODULE: all three modules must resolve `{project}` identically.

WHY THIS FILE EXISTS AT THE REPO ROOT
--------------------------------------
Every other test in this repo lives inside a single module and runs with that
module's directory as cwd, because AGENTS.md requires flat, independent
modules with no cross-imports. That isolation is correct, and it is also
exactly why this bug survived: three modules each had their own
`_project_slug`, each was unit-tested inside its own module, and every one of
those suites passed while the three disagreed with each other.

Nothing inside a single module's tests can catch a disagreement BETWEEN
modules. This file is the seam, and it is the test that would have caught the
defect before a Digital Twin did.

THE DEFECT IT PINS
------------------
All three modules resolve `{project}` in
`~/.amplifier/projects/{project}/preceptor` and must land in the SAME
directory: `hooks-trajectory-observer` WRITES observation records there,
`tool-preceptor` READS and DELETES them, `hooks-cue-injector` reads the
ledger and writes per-session dosing manifests.

For `/root/project` they produced three different answers:

    tool-preceptor  '-root-project'    str.replace, unstripped
    cue-injector    'root-project'     same, then .strip("-")
    observer        'project'          Path(working_dir).name

`.name` and the dashed path coincide only when `working_dir` is a filesystem
root, so the observer and the tool could never agree for any real session.
Measured live: 17 observation records on disk, `preceptor observations`
reporting `total_observations: 0`, and `preceptor forget` returning success
having deleted nothing -- a privacy control reporting success while pointed
at a directory that does not exist.

WHY THE DUPLICATION IS THE RIGHT SHAPE ANYWAY
----------------------------------------------
The obvious fix -- one shared function -- would mean a cross-module import or
a fourth package, both of which AGENTS.md rules out (`modules/*/` is flat,
one `pyproject.toml` each, no `src/`, no shared library). So the three
implementations stay byte-identical by discipline, and this test is the
enforcement. Change one, change all three, or this fails.

    uv run --no-project --with pytest --with pyyaml --with amplifier-core \
        pytest tests/ -q
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]

# Each module directory contains its own package; adding all three to
# sys.path is the least-magic way to load them side by side without
# installing anything or making any module import another.
for _module_dir in (
    "hooks-trajectory-observer",
    "hooks-cue-injector",
    "tool-preceptor",
):
    sys.path.insert(0, str(_REPO_ROOT / "modules" / _module_dir))

import amplifier_module_hooks_cue_injector as injector
import amplifier_module_hooks_trajectory_observer as observer
import amplifier_module_tool_preceptor as tool

# name -> the module's own _project_slug. Keyed by the role each plays in the
# read/write relationship, because that is what makes disagreement a defect.
SLUG_FUNCTIONS = {
    "hooks-trajectory-observer (writes records)": observer._project_slug,
    "tool-preceptor (reads + deletes records)": tool._project_slug,
    "hooks-cue-injector (reads ledger, writes manifests)": injector._project_slug,
}


class _Coordinator:
    """Minimal stand-in exposing only `session.working_dir`."""

    def __init__(self, working_dir: Any) -> None:
        self._working_dir = working_dir

    def get_capability(self, name: str) -> Any:
        if name == "session.working_dir":
            return self._working_dir
        return None


class _RaisingCoordinator:
    """A coordinator whose capability lookup blows up.

    Every module must degrade to the same slug here, not just avoid raising
    -- if one falls back to "default" and another to something else, the
    read/write pair diverges on exactly the sessions where things are
    already going wrong.
    """

    def get_capability(self, name: str) -> Any:
        raise RuntimeError("capability lookup failed")


# The representative set. `/root/project` is the live DTU case that exposed
# the bug; the rest are the shapes most likely to make two implementations
# drift apart again.
WORKING_DIRS: list[tuple[str, Any]] = [
    ("the live DTU case", "/root/project"),
    ("nested path", "/home/alice/dev/some/deep/project"),
    ("path with spaces", "/Users/mj/My Projects/preceptor bundle"),
    ("trailing slash", "/root/project/"),
    ("filesystem root", "/"),
    ("relative path", "project"),
    ("windows-style path", r"C:\Users\mj\project"),
    ("path with a dot-dir", "/home/mj/.amplifier/workspace"),
    ("absent (None)", None),
    ("absent (empty string)", ""),
]


@pytest.mark.parametrize(
    ("label", "working_dir"),
    WORKING_DIRS,
    ids=[label for label, _ in WORKING_DIRS],
)
def test_all_modules_agree_on_the_project_slug(label: str, working_dir: Any) -> None:
    """THE LOAD-BEARING TEST. Same input, same slug, in all three modules."""
    coordinator = _Coordinator(working_dir)
    produced = {name: fn(coordinator) for name, fn in SLUG_FUNCTIONS.items()}

    distinct = set(produced.values())
    assert len(distinct) == 1, (
        f"modules disagree on the {label} ({working_dir!r}): "
        + "; ".join(f"{name} -> {slug!r}" for name, slug in produced.items())
        + ". They resolve the SAME `~/.amplifier/projects/{project}/preceptor` "
        "template, so a disagreement means the observer writes records where "
        "the tool cannot read or delete them."
    )


def test_all_modules_agree_when_the_capability_raises() -> None:
    produced = {name: fn(_RaisingCoordinator()) for name, fn in SLUG_FUNCTIONS.items()}
    assert set(produced.values()) == {"default"}, produced


@pytest.mark.parametrize(
    ("label", "working_dir"),
    WORKING_DIRS,
    ids=[label for label, _ in WORKING_DIRS],
)
def test_slug_is_never_empty_and_never_contains_a_separator(
    label: str, working_dir: Any
) -> None:
    """A slug is interpolated into a path as a single directory component.

    An empty slug collapses `projects/{project}/preceptor` into
    `projects//preceptor`, and a slug still containing `/` silently creates
    a nested tree -- both make two callers land in different places for
    reasons no one would look for.
    """
    for name, fn in SLUG_FUNCTIONS.items():
        slug = fn(_Coordinator(working_dir))
        assert slug, f"{name} produced an empty slug for {working_dir!r}"
        assert "/" not in slug, f"{name} produced {slug!r}, which nests"
        assert "\\" not in slug, f"{name} produced {slug!r}, which nests on Windows"


def test_the_dashed_convention_is_what_amplifier_core_uses() -> None:
    """Pins the specific convention, not merely agreement.

    Three implementations could agree on the WRONG thing. Amplifier core's
    own session directory for a `/root/project` session is
    `/root/.amplifier/projects/-root-project/` -- observed in a live
    container -- leading dash included. That is why the injector's
    `.strip("-")` was wrong rather than merely different, and why the
    observer's `Path(...).name` was too.
    """
    coordinator = _Coordinator("/root/project")
    for name, fn in SLUG_FUNCTIONS.items():
        assert fn(coordinator) == "-root-project", (
            f"{name} does not match amplifier core's own directory convention"
        )


def test_name_based_slugs_would_collide_across_checkouts() -> None:
    """The affirmative case for the dashed form over `Path(...).name`.

    `.name` is not injective: two unrelated checkouts sharing a directory
    name would share one observation store and one ledger, so one person's
    behavioural records would be readable -- and deletable -- from the
    other's session. This test documents the hazard by demonstrating it, so
    a future "simplify this to basename" has to answer it.
    """
    alice, bob = "/home/alice/project", "/home/bob/project"
    assert Path(alice).name == Path(bob).name == "project", (
        "premise of this test no longer holds"
    )
    for name, fn in SLUG_FUNCTIONS.items():
        assert fn(_Coordinator(alice)) != fn(_Coordinator(bob)), (
            f"{name} collides across unrelated checkouts"
        )


if __name__ == "__main__":  # pragma: no cover
    pytest.main([__file__])
