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
import threading
import time
from datetime import datetime, timezone
from itertools import count
from pathlib import Path
from typing import TYPE_CHECKING, Any

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

if TYPE_CHECKING:  # the executor itself is created lazily, on first use
    from concurrent.futures import Future, ThreadPoolExecutor

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

# --- Off-the-critical-path work ------------------------------------------
#
# Hook handlers run sequentially and IN-BAND: whatever a handler does
# synchronously is added to every tool call and every provider request. Two
# things this module does are not cheap: hashing a large tool_input (a 1 MB
# write_file costs ~2 ms of json.dumps + sha256, and it used to be paid
# twice, on tool:pre AND tool:post) and appending a batch to disk (~0.4 ms
# every `flush_every` records). Both now run on ONE shared single-worker
# thread. A single worker is load-bearing: jobs run strictly in submission
# order, so a hash job queued at event time always finishes before the flush
# job that serializes its record, and flushes for one session land in the
# file in the order they were issued.
#
# Durability is unchanged where it matters: the eager flush points
# (execution:end, cancel:requested) and the registered cleanup still BLOCK
# until everything buffered is on disk, exactly as before. Only the
# mid-turn opportunistic flush at `flush_every` is fire-and-forget.

# Inputs whose estimated serialized size is below this are hashed inline --
# a thread hop costs more than hashing a few KB.
_INLINE_HASH_MAX_CHARS = 4096

# Upper bound on how long an eager flush / cleanup waits for the writer.
# Fail open: a hung disk must never hang the session.
_DRAIN_TIMEOUT_S = 10.0

_executor: "ThreadPoolExecutor | None" = None
_executor_lock = threading.Lock()


def _background() -> "ThreadPoolExecutor":
    global _executor
    if _executor is None:
        with _executor_lock:
            if _executor is None:
                from concurrent.futures import ThreadPoolExecutor

                _executor = ThreadPoolExecutor(
                    max_workers=1, thread_name_prefix="preceptor-observer"
                )
    return _executor


def _estimated_chars(value: Any) -> int:
    """Cheap O(top-level keys) size estimate; never serializes anything.

    Only decides WHERE a hash is computed (inline vs. background), never
    WHAT it is, so an underestimate costs latency, not correctness.
    """
    if isinstance(value, str):
        return len(value)
    if isinstance(value, dict):
        total = 0
        for v in value.values():
            if isinstance(v, str):
                total += len(v)
            elif isinstance(v, (dict, list, tuple)):
                total += _INLINE_HASH_MAX_CHARS  # nested: assume large
        return total
    if isinstance(value, (list, tuple)):
        return _INLINE_HASH_MAX_CHARS if len(value) > 64 else 0
    return 0


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
    """In-memory record buffer, flushed to a JSONL file by the background
    writer.

    `add()` never touches disk. `flush(wait=False)` hands the pending batch
    to the writer and returns immediately; `flush(wait=True)` also blocks
    until that batch -- and everything queued before it -- is on disk.
    Records may carry a `Future` in `tool_input_sha256` (a large input being
    hashed off-loop); it is resolved inside the writer job, which the
    single-worker ordering guarantees runs after the hash job.
    """

    def __init__(self, path: Path, flush_every: int = 25) -> None:
        self._path = path
        try:
            self._flush_every = max(1, int(flush_every))
        except (TypeError, ValueError):
            self._flush_every = 25
        self._records: list[dict[str, Any]] = []
        self._last: Future[None] | None = None
        self._dir_ready = False

    def add(self, record: dict[str, Any]) -> None:
        self._records.append(record)
        if len(self._records) >= self._flush_every:
            self.flush(wait=False)

    def flush(self, wait: bool = True) -> None:
        if self._records:
            batch, self._records = self._records, []
            try:
                self._last = _background().submit(self._write, batch)
            except Exception:
                # Executor unavailable (e.g. interpreter shutdown): write inline.
                logger.debug(
                    "trajectory-observer: background writer unavailable; "
                    "writing inline",
                    exc_info=True,
                )
                self._write(batch)
                self._last = None
        if wait:
            self.drain()

    def drain(self) -> None:
        last = self._last
        if last is None:
            return
        try:
            last.result(timeout=_DRAIN_TIMEOUT_S)
        except Exception:
            logger.warning(
                "trajectory-observer: background flush did not complete",
                exc_info=True,
            )

    def _write(self, batch: list[dict[str, Any]]) -> None:
        try:
            for record in batch:
                digest = record.get("tool_input_sha256")
                if digest is not None and not isinstance(digest, str):
                    # A Future from the off-loop hash job, which the
                    # single-worker ordering has already completed.
                    try:
                        record["tool_input_sha256"] = digest.result()
                    except Exception:
                        logger.debug(
                            "trajectory-observer: off-loop hash failed",
                            exc_info=True,
                        )
                        record["tool_input_sha256"] = None
            if not self._dir_ready:
                self._path.parent.mkdir(parents=True, exist_ok=True)
                self._dir_ready = True
            lines = "\n".join(json.dumps(r, sort_keys=True, default=str) for r in batch)
            with open(self._path, "a", encoding="utf-8") as fh:
                fh.write(lines + "\n")
        except Exception:
            logger.exception(
                "trajectory-observer: failed to flush %d record(s) to %s",
                len(batch),
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
        self._cue_ids_final = False
        # tool_call_id -> (tool_input object, digest). loop-streaming passes
        # the SAME `tool_call.arguments` object on tool:pre and tool:post, so
        # the post record reuses the pre record's digest instead of
        # re-serializing a possibly multi-MB input a second time.
        self._pending_digests: dict[Any, tuple[Any, Any]] = {}

    def next_id(self) -> str:
        return f"obs-{next(self._counter)}"

    def cue_ids(self, event: str) -> list[str]:
        """Dosed cue ids from the sibling manifest, read at most twice.

        Read on the first event (a resumed session's manifest already
        exists), and -- if that found nothing -- once more on the first
        `provider:request`. The injector writes the manifest on that same
        emit at priority 20, before this handler (200) runs; the first
        event of a new session (execution:start) precedes it, so a
        read-once cache recorded `[]` for every record of every dosed
        session. After that second look the answer is final.
        """
        if self._cue_ids is None:
            self._cue_ids = _load_dosed_cue_ids(self._root, self._session_id)
            self._cue_ids_final = bool(self._cue_ids)
        elif not self._cue_ids_final and event == "provider:request":
            self._cue_ids = _load_dosed_cue_ids(self._root, self._session_id)
            self._cue_ids_final = True
        return self._cue_ids

    def digest(self, event: str, data: dict[str, Any]) -> Any:
        """sha256 of tool_input: a str, None, or a Future resolved by the
        writer. Same bytes hashed as `_sha256_of` always hashed."""
        tool_input = data.get("tool_input")
        if tool_input is None:
            return None
        call_id = data.get("tool_call_id")
        if call_id is not None and event != "tool:pre":
            cached = self._pending_digests.pop(call_id, None)
            if cached is not None and cached[0] is tool_input:
                return cached[1]
        if _estimated_chars(tool_input) < _INLINE_HASH_MAX_CHARS:
            digest: Any = _sha256_of(tool_input)
        else:
            try:
                digest = _background().submit(_sha256_of, tool_input)
            except RuntimeError:  # executor shut down (interpreter exit)
                digest = _sha256_of(tool_input)
        if call_id is not None and event == "tool:pre":
            if len(self._pending_digests) > 256:  # bound: orphaned pre events
                self._pending_digests.clear()
            self._pending_digests[call_id] = (tool_input, digest)
        return digest

    def observe_resolve(self, data: dict[str, Any]) -> None:
        provider = data.get("provider")
        model = data.get("model")
        if provider is not None:
            self.provider = provider
        if model is not None:
            self.model = model

    def build_record(self, event: str, data: dict[str, Any]) -> dict[str, Any]:
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
            "tool_input_sha256": self.digest(event, data),
            "ok": _derive_ok(event, data),
            "iteration": data.get("iteration"),
            "parallel_group": data.get("parallel_group_id"),
            "cue_ids_dosed": self.cue_ids(event),
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
                buffer.flush(wait=True)
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
            buffer.flush(wait=True)
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
