"""Tests for `forget`'s unconditional availability, and for `surface` as
schema narrowing rather than authority.

THE DEFECT, AND THE FIRST FIX THAT REPEATED IT
-----------------------------------------------
`forget` originally sat in `_WRITE_OPERATIONS`, gated by `writable`, exactly
like `propose_cue`/`promote_cue`/`retire_cue`. Those are MACHINE authority --
they mutate the shared cue ledger on evidence of a measured effect, which is
what `agents/credentialer.md` exists to hold. `forget` is SUBJECT authority:
it deletes a user's own observation records because they asked, authorized by
the records being about them. The only shipped composition that sets
`writable: true` is credentialer, so the deletion right `docs/CONSENT.md` and
`context/awareness.md` promise in every session was unreachable.

The first fix moved `forget` behind a NEW config key, `surface: "consent"`.
That fixed the two adoption bundles and left the full loop (`bundle.md` ->
`behaviors/preceptor.yaml`, which sets no surface) still unable to reach it --
while shipping the promise of `preceptor forget --since <date>` in that very
session. It was the same category error under a new name, and it failed the
same way: a composition that simply omits the key loses the right silently,
which `docs/CONSENT.md` already says is worse than having no control.

`forget` is now gated by NOTHING. `surface` is retained purely to narrow the
advertised JSON schema (a token-cost knob), and every surface contains
`forget` by construction.

    uv run --no-project --with pytest --with pytest-asyncio --with pyyaml \
        pytest tests/test_consent_surface.py -q
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml
from amplifier_module_tool_preceptor import (
    _INPUT_SCHEMA,
    _SUBJECT_OPERATIONS,
    _SURFACES,
    _WRITE_OPERATIONS,
    PreceptorTool,
    mount,
)


class _FakeCoordinator:
    def __init__(self) -> None:
        self.mounted: list[tuple[str, Any, str | None]] = []

    async def mount(self, kind: str, instance: Any, name: str | None = None) -> None:
        self.mounted.append((kind, instance, name))

    def get_capability(self, name: str) -> Any:
        return None


# ---------------------------------------------------------------------------
# THE LOAD-BEARING TESTS: `forget` is reachable from every valid config.
# ---------------------------------------------------------------------------

# Every config shape a composition can produce, including the three that ship:
#
#   {}                        behaviors/preceptor.yaml -- the FULL LOOP, via
#                             bundle.md. Sets neither key. This is the one the
#                             `surface`-gated fix still left broken.
#   {"surface": "consent"}    behaviors/preceptor-consent.yaml -- both
#                             adoption bundles (observe-only, observe-on)
#   {"writable": True}        agents/credentialer.md
#   {"writable": False}       agents/form-analyst.md, skeptic.md, assessor.md
#
# Table-driven so the matrix is visible rather than buried in prose.
FORGET_MUST_WORK_UNDER: list[tuple[str, dict[str, Any]]] = [
    ("full loop (no surface, writable unset)", {}),
    ("adoption bundles (surface: consent)", {"surface": "consent"}),
    ("credentialer (writable: true)", {"writable": True}),
    ("read-only agents (writable: false)", {"writable": False}),
    ("explicit surface: None", {"surface": None}),
    ("both keys set", {"surface": "consent", "writable": True}),
]


@pytest.mark.parametrize(
    ("label", "config"),
    FORGET_MUST_WORK_UNDER,
    ids=[label for label, _ in FORGET_MUST_WORK_UNDER],
)
async def test_forget_succeeds_under_every_config(
    label: str, config: dict[str, Any], tmp_path: Path
) -> None:
    coordinator = _FakeCoordinator()
    tool = PreceptorTool(coordinator, {"root": str(tmp_path), **config})
    result = await tool.execute(
        {"operation": "forget", "since": "2026-01-01T00:00:00Z"}
    )
    assert result.success is True, f"forget must work under {label}; got {result.error}"


def test_forget_is_gated_by_neither_writable_nor_surface() -> None:
    """REGRESSION GUARD -- read this before adding any check on `forget`.

    Two gates have already been shipped on this operation and both were
    removed:

      1. `writable: true` -- held only by `agents/credentialer.md`, whose
         authority is crediting cue-lifecycle EVIDENCE. A user deleting
         their own records is not exercising that authority, so the gate
         made the promised control unreachable from every shipped session.

      2. `surface: "consent"` -- the fix for (1), which fixed the two
         adoption bundles and left the full loop still broken, because
         `behaviors/preceptor.yaml` sets no surface. Same category error,
         new name.

    Both failed in the same direction and for the same reason: a config knob
    whose value decides whether a person may delete data about themselves
    will eventually be omitted by some composition, and omission is SILENT.
    `docs/CONSENT.md` states the principle -- a consent control that fails
    silently is worse than no control at all -- and it applies to this gate
    as much as to the `settings.yaml` recording stanza it was written about.

    There is no composition where "you may be recorded but may not delete"
    is correct. If the bundle records, deletion must work; if it does not
    record, `forget` is harmless because there is nothing to delete.

    So: `forget` belongs to no authority set that any config can withhold.
    If you are adding a third gate, the bar is an argument that defeats the
    two above -- not a new key name.
    """
    assert "forget" in _SUBJECT_OPERATIONS
    assert "forget" not in _WRITE_OPERATIONS
    # Machine authority and subject authority must not overlap. If a future
    # operation seems to need both, that is a sign it is not one operation.
    assert _SUBJECT_OPERATIONS.isdisjoint(_WRITE_OPERATIONS)


def test_every_surface_includes_forget() -> None:
    """THE STRUCTURAL INVARIANT, asserted over `_SURFACES` rather than over
    the one literal that happens to exist today.

    `_SURFACES` is BUILT by unioning `_SUBJECT_OPERATIONS` into every entry
    of `_SURFACE_READS`, so a surface that omits `forget` is unrepresentable
    rather than merely absent. This test is what fails if someone replaces
    that construction with hand-written literals.
    """
    assert _SURFACES, "at least one surface must exist for this to mean anything"
    for name, operations in _SURFACES.items():
        assert _SUBJECT_OPERATIONS <= operations, (
            f"surface {name!r} omits {sorted(_SUBJECT_OPERATIONS - operations)} -- "
            "every surface must carry the subject-authority operations"
        )


async def test_forget_still_works_when_the_surface_does_not_advertise_it() -> None:
    """`surface` narrows the SCHEMA, never the behavior. Even if a surface's
    advertised operation set were somehow missing `forget`, execute() must
    still run it -- the schema is a hint to the model, not a boundary.

    Constructed by mutating the instance's own schema copy after the fact,
    which is the closest reachable analogue of a surface that under-advertises.
    """
    coordinator = _FakeCoordinator()
    tool = PreceptorTool(coordinator, {"root": "/tmp/preceptor-narrowing-test"})
    tool.input_schema["properties"]["operation"]["enum"] = ["status"]
    result = await tool.execute(
        {"operation": "forget", "since": "2026-01-01T00:00:00Z"}
    )
    assert result.success is True


# ---------------------------------------------------------------------------
# Ledger writes ARE still gated -- the machine-authority half is unchanged.
# ---------------------------------------------------------------------------


async def test_ledger_writes_still_require_writable(tmp_path: Path) -> None:
    coordinator = _FakeCoordinator()
    tool = PreceptorTool(coordinator, {"root": str(tmp_path)})
    result = await tool.execute(
        {
            "operation": "propose_cue",
            "provider": "a",
            "model": "m",
            "domain": "d",
            "text": "x",
            "origin": ["obs-1"],
        }
    )
    assert result.success is False
    assert "credentialer" in result.error["message"]


async def test_consent_surface_does_not_grant_ledger_writes(tmp_path: Path) -> None:
    """`surface: consent` is not a back door into machine authority."""
    coordinator = _FakeCoordinator()
    tool = PreceptorTool(coordinator, {"root": str(tmp_path), "surface": "consent"})
    result = await tool.execute(
        {
            "operation": "propose_cue",
            "provider": "a",
            "model": "m",
            "domain": "d",
            "text": "x",
            "origin": ["obs-1"],
        }
    )
    assert result.success is False
    assert "credentialer" in result.error["message"]


# ---------------------------------------------------------------------------
# Construction: unknown surface still fails loudly.
# ---------------------------------------------------------------------------


def test_unknown_surface_raises_naming_valid_surfaces() -> None:
    coordinator = _FakeCoordinator()
    with pytest.raises(ValueError, match="consent"):
        PreceptorTool(coordinator, {"root": "/tmp/x", "surface": "bogus-surface"})


def test_surface_none_is_valid() -> None:
    coordinator = _FakeCoordinator()
    tool = PreceptorTool(coordinator, {"root": "/tmp/x", "surface": None})
    assert tool.surface is None


# ---------------------------------------------------------------------------
# The branched description: every branch must state that deletion works,
# because on every branch it does.
# ---------------------------------------------------------------------------


def test_description_differs_across_surfaces_and_always_mentions_forget(
    tmp_path: Path,
) -> None:
    coordinator = _FakeCoordinator()
    readonly = PreceptorTool(coordinator, {"root": str(tmp_path)})
    consent = PreceptorTool(coordinator, {"root": str(tmp_path), "surface": "consent"})
    writable = PreceptorTool(coordinator, {"root": str(tmp_path), "writable": True})

    descriptions = {readonly.description, consent.description, writable.description}
    assert len(descriptions) == 3, "each surface must get its own description"

    for tool in (readonly, consent, writable):
        assert "forget" in tool.description, (
            f"{tool.surface!r}/writable={tool.writable} description must tell the "
            "model deletion is available -- it is available on every instance"
        )


# ---------------------------------------------------------------------------
# Per-instance schema: never the shared module-level singleton, and its
# `operation` enum reflects the advertised surface.
# ---------------------------------------------------------------------------


def test_schema_is_a_copy_never_the_module_level_singleton(tmp_path: Path) -> None:
    coordinator = _FakeCoordinator()
    tool = PreceptorTool(coordinator, {"root": str(tmp_path)})
    assert tool.input_schema is not _INPUT_SCHEMA
    assert tool.input_schema["properties"] is not _INPUT_SCHEMA["properties"]


def test_schema_enum_is_narrowed_but_always_advertises_forget(
    tmp_path: Path,
) -> None:
    coordinator = _FakeCoordinator()
    readonly = PreceptorTool(coordinator, {"root": str(tmp_path)})
    consent = PreceptorTool(coordinator, {"root": str(tmp_path), "surface": "consent"})
    writable = PreceptorTool(coordinator, {"root": str(tmp_path), "writable": True})

    ro_enum = set(readonly.input_schema["properties"]["operation"]["enum"])
    consent_enum = set(consent.input_schema["properties"]["operation"]["enum"])
    writable_enum = set(writable.input_schema["properties"]["operation"]["enum"])

    # The point of `surface`: real token savings on every provider request.
    assert len(consent_enum) < len(ro_enum) < len(writable_enum)
    assert consent_enum == {"status", "observations", "forget"}

    # ...but narrowing never drops the subject-authority operation.
    for enum in (ro_enum, consent_enum, writable_enum):
        assert "forget" in enum

    assert "propose_cue" not in ro_enum
    assert "propose_cue" not in consent_enum
    assert "propose_cue" in writable_enum


def test_schema_copies_never_alias_each_other_or_the_module_singleton(
    tmp_path: Path,
) -> None:
    """`_INPUT_SCHEMA`'s OWN enum legitimately lists every operation -- it
    describes the tool's full shape, independent of any instance's advertised
    surface. What must never happen is a per-instance COPY sharing the same
    underlying list object as a sibling instance or as `_INPUT_SCHEMA`."""
    coordinator = _FakeCoordinator()
    a = PreceptorTool(coordinator, {"root": str(tmp_path)})
    b = PreceptorTool(coordinator, {"root": str(tmp_path)})

    a_enum = a.input_schema["properties"]["operation"]["enum"]
    b_enum = b.input_schema["properties"]["operation"]["enum"]
    module_enum = _INPUT_SCHEMA["properties"]["operation"]["enum"]

    assert a_enum is not b_enum
    assert a_enum is not module_enum
    assert a.input_schema["properties"] is not _INPUT_SCHEMA["properties"]

    before = list(module_enum)
    a_enum.append("__mutated_marker__")
    assert module_enum == before, (
        "mutating an instance's schema leaked into _INPUT_SCHEMA"
    )
    assert "__mutated_marker__" not in b_enum, (
        "mutating one instance leaked into a sibling"
    )


# ---------------------------------------------------------------------------
# mount()'s descriptor.
# ---------------------------------------------------------------------------


async def test_mount_descriptor_reports_writable_and_surface() -> None:
    coordinator = _FakeCoordinator()
    result = await mount(coordinator, {"root": "/tmp/x", "surface": "consent"})
    assert result["surface"] == "consent"
    assert result["writable"] is False


# ---------------------------------------------------------------------------
# S4 -- one declaration per composition. When the same module is declared
# twice in one bundle composition, the config does not merge: the first
# declaration wins ENTIRE, silently (proven in a Digital Twin --
# behaviors/preceptor-observer-on.yaml:10-25 documents the whole incident).
# `tool-preceptor` is now mountable from TWO different behaviors
# (behaviors/preceptor.yaml and behaviors/preceptor-consent.yaml), so a
# bundle that composed BOTH would silently lose one config. This resolves
# every shipped entry-point bundle's local `includes:` chain and asserts each
# module name appears at most once in the flattened tools:/hooks: list.
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[3]

_ENTRY_POINTS = [
    _REPO_ROOT / "bundle.md",
    _REPO_ROOT / "bundles" / "observe-only.yaml",
    _REPO_ROOT / "bundles" / "observe-on.yaml",
]


def _load_bundle_yaml(path: Path) -> dict[str, Any]:
    """Load the YAML bundle document from a `.yaml` file or a `.md`
    frontmatter block (bundle.md's own shape)."""
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".md":
        match = re.match(r"^---\n(.*?)\n---\n", text, re.DOTALL)
        assert match, f"{path} has no YAML frontmatter block"
        text = match.group(1)
    doc = yaml.safe_load(text)
    return doc or {}


def _resolve_local_include(ref: str) -> Path | None:
    """Resolve a `preceptor:<path>` self-reference to a local file.

    Returns None for anything external (`git+https://...`) -- not resolvable
    offline, and out of this repo's control anyway.
    """
    if not ref.startswith("preceptor:"):
        return None
    rel = ref.removeprefix("preceptor:")
    candidate = _REPO_ROOT / rel
    if candidate.suffix not in (".yaml", ".md"):
        candidate = candidate.with_suffix(".yaml")
    return candidate


def _collect_module_names(path: Path, seen: set[Path] | None = None) -> list[str]:
    """Flatten a bundle's own `tools:`/`hooks:` module names plus every
    locally resolvable include's, recursively."""
    seen = seen if seen is not None else set()
    resolved = path.resolve()
    if resolved in seen:
        return []
    seen.add(resolved)

    doc = _load_bundle_yaml(path)
    names: list[str] = []
    for section in ("tools", "hooks"):
        for entry in doc.get(section) or []:
            module = entry.get("module")
            if module:
                names.append(module)

    for include in doc.get("includes") or []:
        ref = include.get("bundle") if isinstance(include, dict) else None
        if not ref:
            continue
        local = _resolve_local_include(ref)
        if local is not None and local.exists():
            names.extend(_collect_module_names(local, seen))

    return names


@pytest.mark.parametrize("entry", _ENTRY_POINTS, ids=[p.name for p in _ENTRY_POINTS])
def test_no_module_declared_twice_in_one_composition(entry: Path) -> None:
    names = _collect_module_names(entry)
    assert names, f"{entry.name} resolved to zero module declarations -- check the path"
    dupes = {n for n in names if names.count(n) > 1}
    assert not dupes, (
        f"{entry.name} declares {sorted(dupes)} more than once across its "
        "resolved includes -- when the same module is declared twice in one "
        "composition, the config does not merge; the first declaration wins "
        "ENTIRE (proven in a Digital Twin, see "
        "behaviors/preceptor-observer-on.yaml)."
    )


def test_every_shipped_entry_point_mounts_tool_preceptor() -> None:
    """The mounting half of the original defect: `context/awareness.md` ships
    in all three compositions and promises `preceptor forget --since <date>`,
    so all three must actually mount the tool that provides it. Unconditional
    `forget` is necessary but not sufficient -- a tool that is never mounted
    cannot be called either."""
    for entry in _ENTRY_POINTS:
        names = _collect_module_names(entry)
        assert "tool-preceptor" in names, (
            f"{entry.name} does not mount tool-preceptor, but ships context "
            "promising `preceptor forget --since <date>`"
        )


if __name__ == "__main__":  # pragma: no cover
    pytest.main([__file__])
