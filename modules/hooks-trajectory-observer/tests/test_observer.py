"""Tests for the preceptor trajectory observer hook module."""

import hashlib
import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from amplifier_module_hooks_trajectory_observer import OBSERVED_EVENTS, mount


def _make_coordinator(session_id: str = "sess-1") -> MagicMock:
    """Build the MagicMock coordinator exactly as specified: hooks.register,
    register_cleanup, and get_capability are explicit mocks; session_id is a
    plain attribute (mirrors the real RustCoordinator's sync property)."""
    coordinator = MagicMock()
    coordinator.hooks.register = MagicMock()
    coordinator.register_cleanup = MagicMock()
    coordinator.get_capability = MagicMock(return_value=None)
    coordinator.session_id = session_id
    return coordinator


def _registered_handler(coordinator: MagicMock):
    """Return the single handler function shared across all event
    registrations (mount() registers the same closure for every event)."""
    assert coordinator.hooks.register.call_args_list, "no handlers were registered"
    return coordinator.hooks.register.call_args_list[0].args[1]


def _observations_path(root: Path, session_id: str = "sess-1") -> Path:
    return root / "observations" / f"{session_id}.jsonl"


def _read_records(root: Path, session_id: str = "sess-1") -> list[dict[str, Any]]:
    path = _observations_path(root, session_id)
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line
    ]


# ---------------------------------------------------------------------------
# 1. The consent gate -- the single most important behavior in the module.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_disabled_registers_nothing(tmp_path: Path) -> None:
    """enabled defaults to False -- mount() must register NOTHING at all."""
    coordinator = _make_coordinator()

    # No config at all: enabled must default to False.
    await mount(coordinator, None)
    coordinator.hooks.register.assert_not_called()
    coordinator.register_cleanup.assert_not_called()

    # Explicit enabled=False must behave identically to the default.
    await mount(coordinator, {"enabled": False, "root": str(tmp_path)})
    coordinator.hooks.register.assert_not_called()
    coordinator.register_cleanup.assert_not_called()

    # Empty config dict also defaults to disabled.
    await mount(coordinator, {})
    coordinator.hooks.register.assert_not_called()


# ---------------------------------------------------------------------------
# 2. Enabling registers every canonical event.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_enabled_registers_handlers(tmp_path: Path) -> None:
    coordinator = _make_coordinator()

    await mount(coordinator, {"enabled": True, "root": str(tmp_path)})

    assert coordinator.hooks.register.call_count == len(OBSERVED_EVENTS)
    registered_events = {
        call.args[0] for call in coordinator.hooks.register.call_args_list
    }
    assert registered_events == set(OBSERVED_EVENTS)

    # Every registration uses the same handler and the same name/priority.
    for call in coordinator.hooks.register.call_args_list:
        assert call.kwargs["priority"] == 200  # default
        assert call.kwargs["name"] == "preceptor-observer"

    coordinator.register_cleanup.assert_called_once()


@pytest.mark.asyncio
async def test_custom_priority_is_used(tmp_path: Path) -> None:
    coordinator = _make_coordinator()

    await mount(coordinator, {"enabled": True, "root": str(tmp_path), "priority": 42})

    for call in coordinator.hooks.register.call_args_list:
        assert call.kwargs["priority"] == 42


# ---------------------------------------------------------------------------
# 3. Gotcha #1: tool:post carries `tool_name`, never `tool`.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tool_post_uses_tool_name_key(tmp_path: Path) -> None:
    coordinator = _make_coordinator()
    await mount(coordinator, {"enabled": True, "root": str(tmp_path)})
    handler = _registered_handler(coordinator)

    result = await handler(
        "tool:post", {"tool_name": "edit_file", "result": {"success": True}}
    )
    assert result.action == "continue"
    await handler("execution:end", {"status": "completed"})  # force flush

    records = _read_records(tmp_path)
    tool_posts = [r for r in records if r["event"] == "tool:post"]
    assert len(tool_posts) == 1
    assert tool_posts[0]["tool_name"] == "edit_file"

    # The wrong key ("tool" instead of "tool_name") must NEVER populate
    # tool_name -- this guards the gotcha permanently.
    result = await handler(
        "tool:post", {"tool": "edit_file", "result": {"success": True}}
    )
    assert result.action == "continue"
    await handler("execution:end", {"status": "completed"})

    records = _read_records(tmp_path)
    tool_posts = [r for r in records if r["event"] == "tool:post"]
    assert len(tool_posts) == 2
    assert tool_posts[1]["tool_name"] is None


# ---------------------------------------------------------------------------
# 4. Privacy is a hard requirement: no content ever leaks, only a hash.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_content_leaks(tmp_path: Path) -> None:
    coordinator = _make_coordinator()
    await mount(coordinator, {"enabled": True, "root": str(tmp_path)})
    handler = _registered_handler(coordinator)

    secret = "sk-super-secret-XYZ123-do-not-leak"
    tool_input = {"path": "/x", "content": secret}
    await handler(
        "tool:post",
        {
            "tool_name": "edit_file",
            "tool_input": tool_input,
            "result": {"success": True, "output": f"wrote to {secret}"},
        },
    )
    await handler("execution:end", {"status": "completed"})

    raw = _observations_path(tmp_path).read_text(encoding="utf-8")
    assert secret not in raw

    records = _read_records(tmp_path)
    tool_post = next(r for r in records if r["event"] == "tool:post")

    expected_hash = hashlib.sha256(
        json.dumps(tool_input, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()
    assert tool_post["tool_input_sha256"] == expected_hash
    assert len(tool_post["tool_input_sha256"]) == 64
    assert tool_post["ok"] is True

    # No free-text detail/error field exists anywhere in the schema.
    assert "detail" not in tool_post
    assert "error" not in tool_post
    assert set(tool_post.keys()) == {
        "v",
        "id",
        "ts",
        "session",
        "parent",
        "provider",
        "model",
        "event",
        "tool_name",
        "tool_input_sha256",
        "ok",
        "iteration",
        "parallel_group",
        "cue_ids_dosed",
    }


@pytest.mark.asyncio
async def test_no_content_leaks_on_failure_path(tmp_path: Path) -> None:
    """Same guarantee on the failure path (tool:error), where a naive
    implementation might be tempted to record the error message."""
    coordinator = _make_coordinator()
    await mount(coordinator, {"enabled": True, "root": str(tmp_path)})
    handler = _registered_handler(coordinator)

    secret = "super-secret-error-detail-should-not-leak"
    await handler(
        "tool:error",
        {"tool_name": "edit_file", "error": {"message": secret, "type": "OSError"}},
    )
    await handler("execution:end", {"status": "completed"})

    raw = _observations_path(tmp_path).read_text(encoding="utf-8")
    assert secret not in raw

    records = _read_records(tmp_path)
    tool_error = next(r for r in records if r["event"] == "tool:error")
    assert tool_error["ok"] is False


# ---------------------------------------------------------------------------
# 5. Buffer flush guarantees: cleanup callable flushes everything buffered.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_buffer_flushes_on_cleanup(tmp_path: Path) -> None:
    coordinator = _make_coordinator()
    await mount(
        coordinator, {"enabled": True, "root": str(tmp_path), "flush_every": 999}
    )
    handler = _registered_handler(coordinator)

    await handler("tool:pre", {"tool_name": "edit_file"})
    await handler("tool:post", {"tool_name": "edit_file", "result": {"success": True}})

    # Buffer is well under flush_every and neither event is eager-flushed;
    # nothing should be on disk yet.
    assert not _observations_path(tmp_path).exists()

    cleanup = coordinator.register_cleanup.call_args[0][0]
    await cleanup()

    records = _read_records(tmp_path)
    assert len(records) == 2
    assert {r["event"] for r in records} == {"tool:pre", "tool:post"}


@pytest.mark.asyncio
async def test_buffer_flushes_on_flush_every_threshold(tmp_path: Path) -> None:
    coordinator = _make_coordinator()
    await mount(coordinator, {"enabled": True, "root": str(tmp_path), "flush_every": 2})
    handler = _registered_handler(coordinator)

    await handler("tool:pre", {"tool_name": "a"})
    assert not _observations_path(tmp_path).exists()

    await handler("tool:pre", {"tool_name": "b"})  # hits the threshold
    assert len(_read_records(tmp_path)) == 2


@pytest.mark.asyncio
async def test_buffer_flushes_on_cancel_requested(tmp_path: Path) -> None:
    coordinator = _make_coordinator()
    await mount(
        coordinator, {"enabled": True, "root": str(tmp_path), "flush_every": 999}
    )
    handler = _registered_handler(coordinator)

    await handler("tool:pre", {"tool_name": "edit_file"})
    assert not _observations_path(tmp_path).exists()

    await handler("cancel:requested", {})
    records = _read_records(tmp_path)
    assert {r["event"] for r in records} == {"tool:pre", "cancel:requested"}


# ---------------------------------------------------------------------------
# 6. FAIL-OPEN IS ABSOLUTE: the handler never raises, on any input.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handler_never_raises(tmp_path: Path) -> None:
    coordinator = _make_coordinator()
    await mount(coordinator, {"enabled": True, "root": str(tmp_path)})
    handler = _registered_handler(coordinator)

    result = await handler("tool:post", {})
    assert result.action == "continue"

    result = await handler(
        "tool:post",
        {
            "tool_name": 12345,
            "tool_input": ["not", "a", "dict"],
            "result": "not-a-dict-or-model",
            "iteration": object(),
            "parallel_group_id": {"nested": "weird"},
        },
    )
    assert result.action == "continue"

    class _Unstringable:
        def __str__(self) -> str:
            raise RuntimeError("boom")

    result = await handler("tool:post", {"tool_input": _Unstringable()})
    assert result.action == "continue"

    # Even a non-dict event payload must not raise.
    result = await handler("tool:post", None)  # type: ignore[arg-type]
    assert result.action == "continue"

    # And the eager-flush path (which now has to serialize the poisoned
    # records above) must not raise either.
    result = await handler("execution:end", {"status": "completed"})
    assert result.action == "continue"


# ---------------------------------------------------------------------------
# 7. Provider/model are cached from provider:resolve and stamped on every
#    subsequent record (gotcha #3).
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_provider_model_cached_from_resolve(tmp_path: Path) -> None:
    coordinator = _make_coordinator()
    await mount(coordinator, {"enabled": True, "root": str(tmp_path)})
    handler = _registered_handler(coordinator)

    await handler(
        "provider:resolve", {"provider": "anthropic", "model": "claude-opus-5"}
    )
    await handler("tool:post", {"tool_name": "edit_file", "result": {"success": True}})
    await handler("execution:end", {"status": "completed"})

    records = _read_records(tmp_path)
    tool_post = next(r for r in records if r["event"] == "tool:post")
    assert tool_post["provider"] == "anthropic"
    assert tool_post["model"] == "claude-opus-5"

    # provider:request only carries "provider", never "model" -- the cache
    # must not be clobbered back to None by a later provider:request.
    await handler("provider:request", {"provider": "anthropic", "iteration": 1})
    await handler("tool:post", {"tool_name": "edit_file", "result": {"success": True}})
    await handler("execution:end", {"status": "completed"})

    records = _read_records(tmp_path)
    tool_posts = [r for r in records if r["event"] == "tool:post"]
    assert tool_posts[-1]["model"] == "claude-opus-5"


# ---------------------------------------------------------------------------
# Additional coverage: session_id/parent_id merge (gotcha #2), iteration
# passthrough, and root template placeholder substitution.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_session_and_parent_id_recorded_from_payload(tmp_path: Path) -> None:
    coordinator = _make_coordinator(session_id="root-session")
    await mount(coordinator, {"enabled": True, "root": str(tmp_path)})
    handler = _registered_handler(coordinator)

    # The kernel merges session_id/parent_id into every event payload.
    await handler(
        "tool:post",
        {
            "tool_name": "edit_file",
            "result": {"success": True},
            "session_id": "child-session",
            "parent_id": "root-session",
            "iteration": 3,
        },
    )
    await handler(
        "execution:end",
        {"status": "completed", "session_id": "child-session"},
    )

    # Session-scoped file is keyed by the session_id resolved at mount time,
    # not the per-event session_id.
    records = _read_records(tmp_path, session_id="root-session")
    tool_post = next(r for r in records if r["event"] == "tool:post")
    assert tool_post["session"] == "child-session"
    assert tool_post["parent"] == "root-session"
    assert tool_post["iteration"] == 3


@pytest.mark.asyncio
async def test_root_template_placeholders_are_substituted(tmp_path: Path) -> None:
    coordinator = _make_coordinator(session_id="sess-42")
    root_template = str(tmp_path / "{project}" / "preceptor")

    await mount(
        coordinator,
        {"enabled": True, "root": root_template, "record_payload_shapes": False},
    )
    handler = _registered_handler(coordinator)

    await handler("execution:start", {"prompt": "hi"})
    await handler("execution:end", {"status": "completed"})

    expected = tmp_path / "default" / "preceptor" / "observations" / "sess-42.jsonl"
    assert expected.exists()


@pytest.mark.asyncio
async def test_record_payload_shapes_disabled_writes_no_shapes_file(
    tmp_path: Path,
) -> None:
    coordinator = _make_coordinator()
    await mount(
        coordinator,
        {"enabled": True, "root": str(tmp_path), "record_payload_shapes": False},
    )
    handler = _registered_handler(coordinator)

    await handler("tool:pre", {"tool_name": "x"})
    await handler("execution:end", {"status": "completed"})

    assert not (tmp_path / "payload-shapes.json").exists()
    assert _observations_path(tmp_path).exists()


@pytest.mark.asyncio
async def test_record_payload_shapes_enabled_writes_shapes_file(
    tmp_path: Path,
) -> None:
    coordinator = _make_coordinator()
    await mount(coordinator, {"enabled": True, "root": str(tmp_path)})
    handler = _registered_handler(coordinator)

    await handler("tool:pre", {"tool_name": "x", "session_id": "sess-1"})
    await handler("execution:end", {"status": "completed"})

    shapes_path = tmp_path / "payload-shapes.json"
    assert shapes_path.exists()
    shapes = json.loads(shapes_path.read_text(encoding="utf-8"))
    assert "tool:pre" in shapes
    assert "tool_name" in shapes["tool:pre"]


# ---------------------------------------------------------------------------
# No coordinator.register_cleanup: degrade gracefully, don't crash mount().
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_missing_register_cleanup_degrades_gracefully(tmp_path: Path) -> None:
    """A coordinator without register_cleanup must not crash mount() -- the
    module logs a warning and relies on execution:end/cancel:requested."""
    # MagicMock auto-creates any attribute you access, so hasattr() is always
    # True by default. A spec= restricts the mock to only these attributes,
    # making hasattr(limited, "register_cleanup") genuinely False.
    limited = MagicMock(spec=["hooks", "get_capability", "session_id"])
    limited.hooks.register = MagicMock()
    limited.get_capability = MagicMock(return_value=None)
    limited.session_id = "sess-1"

    await mount(limited, {"enabled": True, "root": str(tmp_path)})

    assert limited.hooks.register.call_count == len(OBSERVED_EVENTS)
