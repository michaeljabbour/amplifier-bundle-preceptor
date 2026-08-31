"""Preceptor trajectory observer.

Hook module that appends raw, privacy-scrubbed structural trajectory records
off the model's path -- which events fired, for which tool, with what coarse
outcome -- to a per-session JSONL file. Consent-gated: mounts no handlers at
all unless explicitly enabled. Never gates, modifies, injects context, emits
a user message, or classifies signal. See README.md for the full contract.
"""

__amplifier_module_type__ = "hook"

import hashlib
import json
import logging
import os
import time
from datetime import datetime, timezone
from itertools import count
from pathlib import Path
from typing import Any

# The ecosystem-standard import form. Verified correct against a clean install
# of amplifier-core; deliberately carries NO type-ignore suppression.
#
# If your checker flags these as unknown symbols, the environment is broken, not
# this line: an editable install whose `.pth` points at the amplifier-core repo
# ROOT will let any stray extensionless `amplifier_core/` directory under that
# root win as a PEP 420 namespace package and shadow the real one at
# `python/amplifier_core/`. Symptom: `import amplifier_core; print(__file__)`
# prints `None`. A suppression here would hide that from the next person and
# stay behind forever to hide a real breakage later.
from amplifier_core import HookResult, ModuleCoordinator

logger = logging.getLogger(__name__)

# Canonical events this module observes. Presence in this tuple is the whole
# contract -- registering for an event a given orchestrator never emits is
# harmless, the handler simply never fires for it.
OBSERVED_EVENTS: tuple[str, ...] = (
    "tool:pre",
    "tool:post",
    "tool:error",
    "provider:request",
    "provider:response",
    "provider:retry",
    "provider:error",
    "provider:tool_sequence_repaired",
    "provider:resolve",
    "session:fork",
    "execution:start",
    "execution:end",
    "cancel:requested",
)

# Flush eagerly on these to bound data loss. `session:end` is deliberately
# NOT one of these: on the PyO3 path registered cleanups run BEFORE
# `session:end` is emitted (best-effort, after cleanup), so a handler for it
# would run too late -- and it is not emitted at all on abnormal termination.
# The real guarantees are the registered cleanup callable plus these two
# in-band checkpoints.
_EAGER_FLUSH_EVENTS = frozenset({"execution:end", "cancel:requested"})

_CONTINUE = HookResult(action="continue")


def _sha256_of(value: Any) -> str:
    """Hash a value's JSON form. Returns the hash only -- never the value.

    Used solely so an exact-duplicate call can be detected (a retry-loop
    signal) without ever carrying tool input content.
    """
    try:
        payload = json.dumps(value, sort_keys=True, default=str)
    except Exception:
        logger.debug(
            "trajectory-observer: could not JSON-encode value for hashing; "
            "falling back to str()",
            exc_info=True,
        )
        try:
            payload = str(value)
        except Exception:
            logger.debug(
                "trajectory-observer: value could not be stringified either; "
                "using sentinel hash",
                exc_info=True,
            )
            payload = "unrepresentable"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _result_success(result: Any) -> bool | None:
    """Best-effort success flag from a ToolResult-shaped value.

    Handles both a plain dict payload (``{"success": bool, ...}``) and a
    live ToolResult/pydantic-model instance (``result.success``) -- in-process
    hook dispatch may carry either, since events are not JSON round-tripped
    before Python handlers see them.

    Returns None when no signal can be derived (caller should fall back).
    """
    if result is None:
        return None
    if isinstance(result, dict):
        if "success" in result:
            return bool(result["success"])
        return None
    success = getattr(result, "success", None)
    return bool(success) if success is not None else None


def _derive_ok(event: str, data: dict[str, Any]) -> bool:
    """Coarse boolean outcome signal, never the underlying detail.

    Fails open: True unless an explicit failure signal is present. This is
    deliberately the only outcome signal recorded -- there is no free-text
    detail field; signal classification is an agent's job, not this
    module's, so it must stay changeable without a module release.
    """
    if event in ("tool:error", "provider:error"):
        return False

    success = _result_success(data.get("result"))
    if success is not None:
        return success

    status = data.get("status")
    if isinstance(status, str):
        return status.lower() in ("ok", "success", "completed")

    return not data.get("error")


def _project_slug(coordinator: Any) -> str:
    """Derive the `{project}` slug from the session working directory.

    THIS FUNCTION IS DUPLICATED VERBATIM IN THREE MODULES and must stay
    byte-identical in all of them:

        modules/hooks-trajectory-observer/.../__init__.py   (here)
        modules/tool-preceptor/.../__init__.py
        modules/hooks-cue-injector/.../__init__.py

    The duplication is deliberate -- AGENTS.md requires flat, independent
    modules with no cross-imports -- so the agreement is enforced by
    `tests/test_project_slug_agreement.py` at the repo root, which loads all
    three and asserts they return the same slug for the same input. Change
    one, change all three, or that test fails.

    WHY IT MATTERS: this module WRITES the observation records that
    tool-preceptor READS. Both resolve `{project}` in
    `~/.amplifier/projects/{project}/preceptor`, and they disagreed. This
    function returned `Path(working_dir).name` -> `project` while the tool
    returned the dashed path -> `-root-project`, so the two never pointed at
    the same directory for any real session (they coincide only when
    `working_dir` is a filesystem root). Measured live in a Digital Twin: 17
    records written here, `observations` reporting `total_observations: 0`,
    `forget` returning success having deleted nothing.

    WHY THE DASHED FORM, not `Path(working_dir).name` (what this used to do):

      1. Amplifier core already uses it. `/root/.amplifier/projects/
         -root-project/` exists in a live container as core's own session
         directory, so this convention is the ecosystem's, not ours.
      2. `.name` COLLIDES. `/home/alice/project` and `/home/bob/project`
         both yield `project`, so two unrelated checkouts would share one
         observation store -- one person's records readable, and deletable,
         from the other's session.

    MIGRATION: records this module wrote under the old `.name` slug stay on
    disk at `~/.amplifier/projects/<dirname>/preceptor/` and are NOT read or
    deleted by anything after this change. See docs/CONSENT.md.
    """
    working_dir: Any = None
    try:
        working_dir = coordinator.get_capability("session.working_dir")
    except Exception:
        logger.debug(
            "trajectory-observer: get_capability(session.working_dir) failed",
            exc_info=True,
        )
        working_dir = None
    if not working_dir:
        return "default"
    slug = str(working_dir).replace("\\", "-").replace("/", "-").replace(":", "")
    return slug or "default"


def _resolve_session_id(coordinator: Any) -> str:
    try:
        session_id = coordinator.session_id
    except Exception:
        logger.debug(
            "trajectory-observer: coordinator.session_id access failed",
            exc_info=True,
        )
        session_id = None
    return str(session_id) if session_id else "unknown"


def _resolve_root(root_template: str, project: str, session_id: str) -> Path:
    """Expand the configured root template, falling back to the default on
    any formatting error (e.g. an unknown placeholder in a misconfigured
    template)."""
    try:
        formatted = root_template.format(project=project, session_id=session_id)
    except Exception:
        logger.exception(
            "trajectory-observer: could not format root template %r; using default",
            root_template,
        )
        formatted = f"~/.amplifier/projects/{project}/preceptor"
    return Path(formatted).expanduser()


def _load_dosed_cue_ids(root: Path, session_id: str) -> list[str]:
    """Best-effort read of the sibling dosing manifest. Never raises."""
    manifest_path = root / "manifests" / f"{session_id}.json"
    try:
        if not manifest_path.exists():
            return []
        raw = json.loads(manifest_path.read_text(encoding="utf-8"))
        cues = raw.get("cues") if isinstance(raw, dict) else None
        if not isinstance(cues, list):
            return []
        return [c["id"] for c in cues if isinstance(c, dict) and c.get("id")]
    except Exception:
        logger.debug(
            "trajectory-observer: could not read dosing manifest %s",
            manifest_path,
            exc_info=True,
        )
        return []


def _apply_retention(root: Path, retention_days: Any) -> None:
    """Delete observation files older than retention_days, once at mount.

    A retention failure must never block mount -- wrapped entirely.
    """
    try:
        observations_dir = root / "observations"
        if not observations_dir.is_dir():
            return
        cutoff = time.time() - (float(retention_days) * 86400)
        for path in observations_dir.glob("*.jsonl"):
            try:
                if path.stat().st_mtime < cutoff:
                    path.unlink()
            except OSError:
                logger.debug(
                    "trajectory-observer: could not remove expired file %s",
                    path,
                    exc_info=True,
                )
    except Exception:
        logger.exception("trajectory-observer: retention sweep failed")


class _ObservationBuffer:
    """In-memory record buffer, flushed opportunistically to a JSONL file."""

    def __init__(self, path: Path, flush_every: int = 25) -> None:
        self._path = path
        try:
            self._flush_every = max(1, int(flush_every))
        except (TypeError, ValueError):
            self._flush_every = 25
        self._records: list[dict[str, Any]] = []

    def add(self, record: dict[str, Any]) -> None:
        self._records.append(record)
        if len(self._records) >= self._flush_every:
            self.flush()

    def flush(self) -> None:
        if not self._records:
            return
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            lines = "\n".join(
                json.dumps(r, sort_keys=True, default=str) for r in self._records
            )
            with open(self._path, "a", encoding="utf-8") as fh:
                fh.write(lines + "\n")
            self._records.clear()
        except Exception:
            logger.exception(
                "trajectory-observer: failed to flush %d record(s) to %s",
                len(self._records),
                self._path,
            )


class _ShapeTracker:
    """One-time payload-key discovery: event name -> observed top-level keys.

    Event payloads are untyped dict literals with no schema and no tests
    behind them -- this dumps what actually arrives so it can be trusted
    before it is relied upon.
    """

    def __init__(self, path: Path) -> None:
        self._path = path
        self._shapes: dict[str, set[str]] = {}
        self._dirty = False

    def observe(self, event: str, data: dict[str, Any]) -> None:
        try:
            keys = set(data.keys())
        except Exception:
            logger.debug(
                "trajectory-observer: could not enumerate payload keys for event %r",
                event,
                exc_info=True,
            )
            return
        existing = self._shapes.setdefault(event, set())
        if not keys.issubset(existing):
            existing.update(keys)
            self._dirty = True

    def flush(self) -> None:
        if not self._dirty:
            return
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            serializable = {k: sorted(v) for k, v in self._shapes.items()}
            self._path.write_text(
                json.dumps(serializable, indent=2, sort_keys=True, default=str),
                encoding="utf-8",
            )
            self._dirty = False
        except Exception:
            logger.exception(
                "trajectory-observer: failed to write payload shapes to %s",
                self._path,
            )


class _SessionState:
    """Mutable per-session state shared across handler invocations.

    Caches the (provider, model) pair from `provider:resolve` -- the only
    event that reliably carries both -- and stamps every subsequent record
    from that cache rather than each event's own (inconsistent) payload.
    """

    def __init__(self, root: Path, session_id: str) -> None:
        self._root = root
        self._session_id = session_id
        self._counter = count(1)
        self.provider: str | None = None
        self.model: str | None = None
        self._cue_ids: list[str] | None = None

    def next_id(self) -> str:
        return f"obs-{next(self._counter)}"

    def cue_ids(self) -> list[str]:
        if self._cue_ids is None:
            self._cue_ids = _load_dosed_cue_ids(self._root, self._session_id)
        return self._cue_ids

    def observe_resolve(self, data: dict[str, Any]) -> None:
        provider = data.get("provider")
        model = data.get("model")
        if provider is not None:
            self.provider = provider
        if model is not None:
            self.model = model

    def build_record(self, event: str, data: dict[str, Any]) -> dict[str, Any]:
        tool_input = data.get("tool_input")
        return {
            "v": 1,
            "id": self.next_id(),
            "ts": _now_iso(),
            "session": data.get("session_id", self._session_id),
            "parent": data.get("parent_id"),
            "provider": self.provider,
            "model": self.model,
            "event": event,
            "tool_name": data.get("tool_name"),
            "tool_input_sha256": (
                _sha256_of(tool_input) if tool_input is not None else None
            ),
            "ok": _derive_ok(event, data),
            "iteration": data.get("iteration"),
            "parallel_group": data.get("parallel_group_id"),
            "cue_ids_dosed": self.cue_ids(),
        }


async def mount(coordinator: ModuleCoordinator, config: dict[str, Any] | None = None):
    """Mount the trajectory observer hook.

    Args:
        coordinator: Module coordinator for hook registration and capability
            lookup.
        config: Optional configuration:
            - enabled: Consent gate (default: False). If falsy, no handlers
              are registered at all and this function returns immediately.
            - root: Base directory template (default:
              "~/.amplifier/projects/{project}/preceptor"). "{project}" and
              "{session_id}" are str.format placeholders.
            - flush_every: Buffer size before an opportunistic flush
              (default: 25).
            - retention_days: Delete observations/*.jsonl older than this,
              once at mount (default: 90).
            - priority: Hook registration priority (default: 200).
            - record_payload_shapes: Also write a one-time payload-key
              discovery dump (default: True).

    Returns:
        None. Cleanup is registered directly via
        `coordinator.register_cleanup()`, not via this function's return
        value.
    """
    config = config or {}

    # Consent has TWO paths, and the environment variable is not a convenience --
    # it is the one that provably works.
    #
    # The bundle-config path (`config.enabled` from a behavior YAML) is correct in
    # principle and was the original sole mechanism. It has now failed in a
    # Digital Twin in two distinct ways: first because a duplicate module
    # declaration let an included behavior's `enabled: false` win entire over a
    # root-level override, and then -- after that was fixed and the composition
    # verified correct (hook present exactly once, source path resolving, module
    # importable) -- because mount() was simply never called at all. Both failures
    # were silent: no error, no records, and no way for a user to tell whether
    # they had opted in.
    #
    # So consent does not depend on composition semantics. PRECEPTOR_ENABLED=1 is
    # explicit, per-session, impossible to set by accident, and trivially
    # verifiable by the person setting it. Either path turns recording on; the
    # default remains off.
    env_consent = os.environ.get("PRECEPTOR_ENABLED", "").strip().lower() in (
        "1",
        "true",
        "yes",
    )
    if not (config.get("enabled", False) or env_consent):
        logger.info(
            "trajectory-observer: disabled; registering no handlers "
            "(set PRECEPTOR_ENABLED=1 or config.enabled to record)"
        )
        return

    root_template = os.environ.get("PRECEPTOR_ROOT") or config.get(
        "root", "~/.amplifier/projects/{project}/preceptor"
    )
    flush_every = int(
        os.environ.get("PRECEPTOR_FLUSH_EVERY") or config.get("flush_every", 25)
    )
    retention_days = config.get("retention_days", 90)
    priority = config.get("priority", 200)
    record_payload_shapes = config.get("record_payload_shapes", True)

    project = _project_slug(coordinator)
    session_id = _resolve_session_id(coordinator)
    root = _resolve_root(root_template, project, session_id)

    _apply_retention(root, retention_days)

    buffer = _ObservationBuffer(
        root / "observations" / f"{session_id}.jsonl", flush_every=flush_every
    )
    shapes = (
        _ShapeTracker(root / "payload-shapes.json") if record_payload_shapes else None
    )
    state = _SessionState(root, session_id)

    async def handler(event: str, data: dict[str, Any]) -> HookResult:
        try:
            payload = data if isinstance(data, dict) else {}

            if event == "provider:resolve":
                state.observe_resolve(payload)

            if shapes is not None:
                shapes.observe(event, payload)

            buffer.add(state.build_record(event, payload))

            if event in _EAGER_FLUSH_EVENTS:
                buffer.flush()
                if shapes is not None:
                    shapes.flush()
        except Exception:
            # Fail open, always. A failure here must never cost the user a
            # session -- observation is a side effect, not the main flow.
            logger.exception("trajectory-observer: handler failed for event %r", event)
        return _CONTINUE

    for event in OBSERVED_EVENTS:
        coordinator.hooks.register(
            event, handler, priority=priority, name="preceptor-observer"
        )

    async def cleanup() -> None:
        try:
            buffer.flush()
            if shapes is not None:
                shapes.flush()
        except Exception:
            logger.exception("trajectory-observer: cleanup flush failed")

    if hasattr(coordinator, "register_cleanup"):
        try:
            coordinator.register_cleanup(cleanup)
        except Exception:
            logger.warning(
                "trajectory-observer: register_cleanup failed; relying on "
                "execution:end/cancel:requested flush points",
                exc_info=True,
            )
    else:
        logger.warning(
            "trajectory-observer: coordinator has no register_cleanup; relying "
            "on execution:end/cancel:requested flush points"
        )

    return
