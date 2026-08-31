"""Tests for mount() protocol compliance and the tool's read/write access split."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from amplifier_module_tool_preceptor import PreceptorTool, mount


class _FakeCoordinator:
    def __init__(self) -> None:
        self.mounted: list[tuple[str, Any, str | None]] = []

    async def mount(self, kind: str, instance: Any, name: str | None = None) -> None:
        self.mounted.append((kind, instance, name))

    def get_capability(self, name: str) -> Any:
        return None


async def test_mount_registers_tool():
    coordinator = _FakeCoordinator()
    result = await mount(coordinator, {"root": "/tmp/preceptor-mount-test"})

    assert result is not None
    assert isinstance(result, dict)
    assert coordinator.mounted, "coordinator.mount was never called"

    kind, instance, name = coordinator.mounted[0]
    assert kind == "tools"
    assert name == "preceptor"
    assert isinstance(instance, PreceptorTool)


async def test_tool_has_required_properties():
    coordinator = _FakeCoordinator()
    tool = PreceptorTool(coordinator, {"root": "/tmp/preceptor-mount-test"})

    assert tool.name == "preceptor"
    assert isinstance(tool.description, str) and tool.description
    assert isinstance(tool.input_schema, dict)
    assert callable(tool.execute)


async def test_readonly_refuses_writes(tmp_path):
    """Every LEDGER-WRITE operation is refused without `writable: true`.

    `forget` is deliberately NOT in this list, and used to be. It deletes a
    user's own observation records on their own request -- subject authority,
    not the machine authority `writable` gates -- and it is now unconditional.
    See tests/test_consent_surface.py, whose
    test_forget_is_gated_by_neither_writable_nor_surface carries the full
    argument and the two gates that were tried and removed.
    """
    coordinator = _FakeCoordinator()
    tool = PreceptorTool(coordinator, {"root": str(tmp_path), "writable": False})

    write_ops = [
        {
            "operation": "propose_cue",
            "provider": "a",
            "model": "m",
            "domain": "d",
            "text": "x",
            "origin": ["obs-1"],
        },
        {
            "operation": "promote_cue",
            "provider": "a",
            "model": "m",
            "domain": "d",
            "cue_id": "cue-001",
            "entry_evidence": "run-1",
        },
        {
            "operation": "shadow_cue",
            "provider": "a",
            "model": "m",
            "domain": "d",
            "cue_id": "cue-001",
        },
        {
            "operation": "retire_cue",
            "provider": "a",
            "model": "m",
            "domain": "d",
            "cue_id": "cue-001",
            "exit_evidence": "run-2",
        },
        {
            "operation": "restore_cue",
            "provider": "a",
            "model": "m",
            "domain": "d",
            "cue_id": "cue-001",
        },
        {
            "operation": "pin_cue",
            "provider": "a",
            "model": "m",
            "domain": "d",
            "cue_id": "cue-001",
        },
        {
            "operation": "mute_cue",
            "provider": "a",
            "model": "m",
            "domain": "d",
            "cue_id": "cue-001",
        },
        {
            "operation": "log_assessment",
            "run": "r1",
            "provider": "a",
            "model": "m",
            "domain": "d",
            "probes": ["p"],
            "verdict": "positive",
            "n_per_arm": 5,
            "mean": 0.1,
            "variance": 0.01,
        },
    ]

    for op in write_ops:
        result = await tool.execute(op)
        assert result.success is False, (
            f"{op['operation']} should be refused when read-only"
        )
        assert "credentialer" in result.error["message"]


def _unlock_autonomy(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    state = {
        "v": 1,
        "fade_attempts": 40,
        "shadow_restores": 0,
        "false_fade_rate": 0.0,
        "detector_calibrated": True,
        "detector_precision": 0.9,
        "detector_recall": 0.9,
        "autonomy_unlocked": True,
    }
    (root / "state.json").write_text(json.dumps(state), encoding="utf-8")


async def test_why_reads_manifest_not_ledger(tmp_path):
    root = tmp_path / "preceptor"
    obs_dir = root / "observations"
    obs_dir.mkdir(parents=True)
    (obs_dir / "sess-1.jsonl").write_text(
        json.dumps({"id": "obs-1", "ts": "2026-01-01T00:00:00Z"}) + "\n",
        encoding="utf-8",
    )
    _unlock_autonomy(root)

    coordinator = _FakeCoordinator()
    tool = PreceptorTool(
        coordinator,
        {
            "root": str(root),
            "writable": True,
            "autonomous": True,
            "min_fade_attempts": 40,
            "false_fade_ceiling": 0.10,
        },
    )

    propose_result = await tool.execute(
        {
            "operation": "propose_cue",
            "provider": "a",
            "model": "m",
            "domain": "d",
            "text": "Original dosed text.",
            "origin": ["obs-1"],
        }
    )
    assert propose_result.success is True
    cue_id = propose_result.output["id"]

    log_result = await tool.execute(
        {
            "operation": "log_assessment",
            "run": "run-1",
            "provider": "a",
            "model": "m",
            "domain": "d",
            "probes": ["p1"],
            "verdict": "positive",
            "n_per_arm": 5,
            "mean": 0.4,
            "variance": 0.01,
        }
    )
    assert log_result.success is True

    promote_result = await tool.execute(
        {
            "operation": "promote_cue",
            "provider": "a",
            "model": "m",
            "domain": "d",
            "cue_id": cue_id,
            "entry_evidence": "run-1",
        }
    )
    assert promote_result.success is True
    assert promote_result.output["status"] == "active"

    # Manifests are written by the injector at dose time, not by this tool --
    # write one by hand capturing the ORIGINAL text as it was dosed.
    manifests_dir = root / "manifests"
    manifests_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "v": 1,
        "session": "sess-old",
        "ts": "2026-01-01T00:00:00Z",
        "ledger_version": 1,
        "provider": "a",
        "model": "m",
        "domain": "d",
        "cues": [
            {
                "id": cue_id,
                "text": "Original dosed text.",
                "sha256": "irrelevant-for-this-test",
                "dosed_at": "session-start",
            }
        ],
    }
    (manifests_dir / "sess-old.json").write_text(json.dumps(manifest), encoding="utf-8")

    # Now retire the cue from the LIVE ledger with fresh evidence.
    shadow_result = await tool.execute(
        {
            "operation": "shadow_cue",
            "provider": "a",
            "model": "m",
            "domain": "d",
            "cue_id": cue_id,
        }
    )
    assert shadow_result.success is True

    log_result_2 = await tool.execute(
        {
            "operation": "log_assessment",
            "run": "run-2",
            "provider": "a",
            "model": "m",
            "domain": "d",
            "probes": ["p2"],
            "verdict": "no-effect",
            "n_per_arm": 5,
            "mean": 0.0,
            "variance": 0.01,
        }
    )
    assert log_result_2.success is True

    retire_result = await tool.execute(
        {
            "operation": "retire_cue",
            "provider": "a",
            "model": "m",
            "domain": "d",
            "cue_id": cue_id,
            "exit_evidence": "run-2",
        }
    )
    assert retire_result.success is True
    assert retire_result.output["status"] == "faded"

    # "why" for the OLD session must still return the ORIGINAL dosed text from the
    # manifest, even though the live ledger has since retired the cue entirely.
    why_result = await tool.execute({"operation": "why", "session_id": "sess-old"})
    assert why_result.success is True
    assert why_result.output["cues"][0]["text"] == "Original dosed text."


async def test_unknown_operation_lists_valid_ones():
    coordinator = _FakeCoordinator()
    tool = PreceptorTool(coordinator, {"root": "/tmp/preceptor-mount-test"})
    result = await tool.execute({"operation": "not_a_real_operation"})
    assert result.success is False
    assert "status" in result.error["message"]


async def test_missing_required_field_message_teaches(tmp_path):
    coordinator = _FakeCoordinator()
    tool = PreceptorTool(coordinator, {"root": str(tmp_path), "writable": True})
    result = await tool.execute(
        {
            "operation": "retire_cue",
            "provider": "a",
            "model": "m",
            "domain": "d",
            "cue_id": "cue-001",
        }
    )
    assert result.success is False
    assert "exit_evidence" in result.error["message"]


if __name__ == "__main__":  # pragma: no cover
    pytest.main([__file__])
