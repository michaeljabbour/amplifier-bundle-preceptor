"""Preceptor ledger tool -- mount() entry point and the Tool implementation.

Reads and (when writable) mutates the evidence-gated cue ledger described in
context/methodology/ledger-format.md. See README.md for the full operation
reference, the read/write split, and the autonomy lock.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from amplifier_core import ToolResult

from . import gates, ledger

logger = logging.getLogger(__name__)

__amplifier_module_type__ = "tool"

_DEFAULT_ROOT = "~/.amplifier/projects/{project}/preceptor"

_WRITE_OPERATIONS = frozenset(
    {
        "propose_cue",
        "promote_cue",
        "shadow_cue",
        "retire_cue",
        "restore_cue",
        "pin_cue",
        "mute_cue",
        "log_assessment",
        "forget",
    }
)

# operation -> required top-level fields. `operation` itself is the only field the
# JSON schema marks required; everything else is enforced here at runtime because
# JSON Schema cannot portably express "required conditional on operation" across
# providers.
_REQUIRED_FIELDS: dict[str, tuple[str, ...]] = {
    "status": (),
    "cues": (),
    "why": ("session_id",),
    "observations": (),
    "read_profile": ("provider", "model", "domain"),
    "propose_cue": ("provider", "model", "domain", "text", "origin"),
    "promote_cue": ("provider", "model", "domain", "cue_id", "entry_evidence"),
    "shadow_cue": ("provider", "model", "domain", "cue_id"),
    "retire_cue": ("provider", "model", "domain", "cue_id", "exit_evidence"),
    "restore_cue": ("provider", "model", "domain", "cue_id"),
    "pin_cue": ("provider", "model", "domain", "cue_id"),
    "mute_cue": ("provider", "model", "domain", "cue_id"),
    "log_assessment": (
        "run",
        "provider",
        "model",
        "domain",
        "probes",
        "verdict",
        "n_per_arm",
        "mean",
        "variance",
    ),
    "forget": ("since",),
}

# Extra teaching text appended to a "missing required field" error for fields whose
# absence reflects a design invariant worth restating, not just a shape mismatch.
_MISSING_FIELD_HINTS: dict[str, str] = {
    "exit_evidence": (
        "A cue is never removed on judgment alone -- supply an assessment run id with a "
        "confident no-effect verdict."
    ),
    "entry_evidence": (
        "A cue is never promoted on judgment alone -- supply an assessment run id with a "
        "strictly positive, adequately powered verdict."
    ),
    "origin": (
        "A cue must be traceable to observations that actually occurred -- supply the "
        "observation ids it was derived from."
    ),
}

# Fields where 0 (or an empty-looking-but-valid value) is legitimate, not "missing".
_NUMERIC_FIELDS = frozenset({"n_per_arm", "mean", "variance", "limit"})
_LIST_FIELDS = frozenset({"origin", "probes"})

_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "operation": {
            "type": "string",
            "enum": sorted(_REQUIRED_FIELDS),
            "description": "Which preceptor ledger operation to perform.",
        },
        "provider": {
            "type": "string",
            "description": "LLM provider id, e.g. 'anthropic'.",
        },
        "model": {"type": "string", "description": "Model id, e.g. 'claude-opus-5'."},
        "domain": {
            "type": "string",
            "description": "Domain identifier, e.g. 'python-implementation'.",
        },
        "session_id": {"type": "string", "description": "Session id (for 'why')."},
        "limit": {
            "type": "integer",
            "description": "Bound on files scanned (for 'observations').",
        },
        "text": {"type": "string", "description": "Cue text (for 'propose_cue')."},
        "origin": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Observation ids this cue is traceable to.",
        },
        "cue_id": {"type": "string", "description": "Cue id, e.g. 'cue-017'."},
        "entry_evidence": {
            "type": "string",
            "description": "Assessment run id showing a positive delta.",
        },
        "exit_evidence": {
            "type": "string",
            "description": "Assessment run id showing a confident no-effect.",
        },
        "run": {
            "type": "string",
            "description": "Assessment run id (for 'log_assessment').",
        },
        "probes": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Probe identifiers used in this assessment.",
        },
        "verdict": {
            "type": "string",
            "enum": ["positive", "no-effect", "inconclusive"],
            "description": "Pre-registered judgment of the assessment.",
        },
        "n_per_arm": {
            "type": "integer",
            "description": "Runs per arm (minimum 5 to gate anything).",
        },
        "mean": {"type": "number", "description": "Mean effect observed."},
        "variance": {
            "type": "number",
            "description": "Variance of the observed effect.",
        },
        "since": {
            "type": "string",
            "description": "ISO-8601 date/datetime (for 'forget').",
        },
    },
    "required": ["operation"],
}


def _get_capability_safe(coordinator: Any, name: str) -> Any:
    if coordinator is None:
        return None
    get_capability = getattr(coordinator, "get_capability", None)
    if not callable(get_capability):
        return None
    try:
        return get_capability(name)
    except Exception:  # noqa: BLE001 -- capability lookup must never break mount()
        return None


def _project_slug(coordinator: Any) -> str | None:
    working_dir = _get_capability_safe(coordinator, "session.working_dir")
    if not working_dir:
        return None
    text = str(working_dir)
    slug = text.replace("/", "-").replace("\\", "-").replace(":", "")
    return slug or None


def _working_dir(coordinator: Any) -> Path:
    working_dir = _get_capability_safe(coordinator, "session.working_dir")
    if working_dir:
        return Path(working_dir)
    return Path.cwd()


def _is_missing(field: str, data: dict[str, Any]) -> bool:
    if field not in data:
        return True
    value = data[field]
    if value is None:
        return True
    if field in _NUMERIC_FIELDS:
        return False  # present and not None -- 0 is a legitimate value
    if field in _LIST_FIELDS:
        return not isinstance(value, list) or len(value) == 0
    if isinstance(value, str):
        return value.strip() == ""
    return False


class PreceptorTool:
    """The `preceptor` tool: reads and (when writable) mutates the evidence-gated
    cue ledger. See README.md for the full operation reference."""

    def __init__(self, coordinator: Any, config: dict[str, Any]) -> None:
        self._coordinator = coordinator
        self._writable = bool(config.get("writable", False))
        self._autonomous = bool(config.get("autonomous", False))
        self._false_fade_ceiling = float(config.get("false_fade_ceiling", 0.10))
        self._min_fade_attempts = int(config.get("min_fade_attempts", 40))
        self._shadow_window_days = int(config.get("shadow_window_days", 30))
        self._shadow_window_opportunities = int(
            config.get("shadow_window_opportunities", 40)
        )
        self._max_active_cues = int(config.get("max_active_cues", 8))
        self._max_cue_chars = int(config.get("max_cue_chars", 200))

        project_slug = _project_slug(coordinator)
        self._root = ledger.resolve_root(
            config.get("root", _DEFAULT_ROOT), project_slug
        )
        self._working_dir = _working_dir(coordinator)

    @property
    def name(self) -> str:
        return "preceptor"

    @property
    def description(self) -> str:
        return (
            "Read and (when writable) mutate the preceptor evidence-gated cue ledger: "
            "per-model/domain instruction cues that are proposed, promoted, shadowed, "
            "retired, or restored based on measured evidence, never on judgment alone. "
            "Reads are always available; writes require the credentialer agent's "
            "write-mounted instance."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return _INPUT_SCHEMA

    @property
    def _autonomy_cfg(self) -> dict[str, Any]:
        return {
            "autonomous": self._autonomous,
            "min_fade_attempts": self._min_fade_attempts,
            "false_fade_ceiling": self._false_fade_ceiling,
        }

    async def execute(self, input: dict[str, Any]) -> ToolResult:
        try:
            operation = input.get("operation")
            if not isinstance(operation, str) or not operation:
                return ToolResult(
                    success=False,
                    error={"message": "operation is required and must be a string."},
                )
            if operation not in _REQUIRED_FIELDS:
                valid = ", ".join(sorted(_REQUIRED_FIELDS))
                return ToolResult(
                    success=False,
                    error={
                        "message": f"Unknown operation {operation!r}. Valid operations: {valid}."
                    },
                )

            missing = [f for f in _REQUIRED_FIELDS[operation] if _is_missing(f, input)]
            if missing:
                hints = " ".join(
                    _MISSING_FIELD_HINTS[f]
                    for f in missing
                    if f in _MISSING_FIELD_HINTS
                )
                message = f"Operation {operation!r} requires {missing}."
                if hints:
                    message = f"{message} {hints}"
                return ToolResult(success=False, error={"message": message})

            if operation in _WRITE_OPERATIONS and not self._writable:
                return ToolResult(
                    success=False,
                    error={
                        "message": (
                            f"Operation {operation!r} requires write access to the preceptor "
                            "ledger. Only the credentialer agent holds write access "
                            "(writable: true) -- this instance is read-only."
                        )
                    },
                )

            return await self._dispatch(operation, input)
        except ledger.LedgerError as exc:
            return ToolResult(success=False, error={"message": str(exc)})
        except Exception as exc:
            logger.exception("preceptor tool operation failed")
            return ToolResult(
                success=False, error={"message": f"Unexpected error: {exc}"}
            )

    async def _dispatch(self, operation: str, data: dict[str, Any]) -> ToolResult:
        root = self._root
        wd = self._working_dir

        if operation == "status":
            return ToolResult(
                success=True, output=ledger.read_status(root, working_dir=wd)
            )

        if operation == "cues":
            cues = ledger.list_cues(
                root,
                data.get("provider"),
                data.get("model"),
                data.get("domain"),
                working_dir=wd,
            )
            return ToolResult(success=True, output={"cues": cues})

        if operation == "why":
            manifest = ledger.read_manifest(root, data["session_id"])
            return ToolResult(success=True, output=manifest)

        if operation == "observations":
            summary = ledger.summarize_observations(
                root, data.get("session_id"), data.get("limit")
            )
            return ToolResult(success=True, output=summary)

        if operation == "read_profile":
            doc = ledger.read_profile(
                root, data["provider"], data["model"], data["domain"], working_dir=wd
            )
            return ToolResult(success=True, output=doc)

        if operation == "propose_cue":
            cue = ledger.propose_cue(
                root,
                data["provider"],
                data["model"],
                data["domain"],
                data["text"],
                data["origin"],
                max_cue_chars=self._max_cue_chars,
                max_active_cues=self._max_active_cues,
                working_dir=wd,
            )
            return ToolResult(success=True, output=cue)

        if operation == "promote_cue":
            unlocked, reason = gates.autonomy_unlocked(
                ledger.read_state(root), self._autonomy_cfg
            )
            cue = ledger.promote_cue(
                root,
                data["provider"],
                data["model"],
                data["domain"],
                data["cue_id"],
                data["entry_evidence"],
                max_active_cues=self._max_active_cues,
                working_dir=wd,
                dry_run=not unlocked,
            )
            if unlocked:
                return ToolResult(success=True, output=cue)
            return ToolResult(
                success=True,
                output={"locked": True, "reason": reason, "proposed_diff": cue},
            )

        if operation == "shadow_cue":
            cue = ledger.shadow_cue(
                root,
                data["provider"],
                data["model"],
                data["domain"],
                data["cue_id"],
                cfg=self._autonomy_cfg,
                working_dir=wd,
            )
            return ToolResult(success=True, output=cue)

        if operation == "retire_cue":
            unlocked, reason = gates.autonomy_unlocked(
                ledger.read_state(root), self._autonomy_cfg
            )
            cue = ledger.retire_cue(
                root,
                data["provider"],
                data["model"],
                data["domain"],
                data["cue_id"],
                data["exit_evidence"],
                working_dir=wd,
                dry_run=not unlocked,
            )
            if unlocked:
                return ToolResult(success=True, output=cue)
            return ToolResult(
                success=True,
                output={"locked": True, "reason": reason, "proposed_diff": cue},
            )

        if operation == "restore_cue":
            cue = ledger.restore_cue(
                root,
                data["provider"],
                data["model"],
                data["domain"],
                data["cue_id"],
                cfg=self._autonomy_cfg,
                working_dir=wd,
            )
            return ToolResult(success=True, output=cue)

        if operation == "pin_cue":
            cue = ledger.pin_cue(
                root,
                data["provider"],
                data["model"],
                data["domain"],
                data["cue_id"],
                working_dir=wd,
            )
            return ToolResult(success=True, output=cue)

        if operation == "mute_cue":
            cue = ledger.mute_cue(
                root,
                data["provider"],
                data["model"],
                data["domain"],
                data["cue_id"],
                working_dir=wd,
            )
            return ToolResult(success=True, output=cue)

        if operation == "log_assessment":
            record = ledger.log_assessment(
                root,
                data["run"],
                data["provider"],
                data["model"],
                data["domain"],
                data["probes"],
                data["verdict"],
                data["n_per_arm"],
                data["mean"],
                data["variance"],
            )
            return ToolResult(success=True, output=record)

        if operation == "forget":
            result = ledger.forget(root, data["since"])
            return ToolResult(success=True, output=result)

        # Unreachable: `operation` was already validated against _REQUIRED_FIELDS above.
        raise AssertionError(f"unhandled operation {operation!r}")


async def mount(
    coordinator: Any, config: dict[str, Any] | None = None
) -> dict[str, Any]:
    config = config or {}
    tool = PreceptorTool(coordinator, config)
    await coordinator.mount("tools", tool, name=tool.name)  # REQUIRED
    return {"name": "tool-preceptor", "version": "0.1.0", "provides": ["preceptor"]}
