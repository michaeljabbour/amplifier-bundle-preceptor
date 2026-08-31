"""Preceptor cue injector.

Doses evidence-backed cues from the preceptor ledger into a session's first
`provider:request` event, with a human-visible receipt and an immutable
dosing manifest for provenance.

Design notes (see README.md for the full contract):

- Registers on ``provider:request`` (configurable), which fires *before*
  messages are fetched, specifically to allow injection, and is uncontested
  in the default hook stack. ``tool:pre`` is gated by ``hooks-approval``,
  and hook precedence is ``deny > ask_user > inject_context > modify >
  continue`` -- an ``ask_user`` anywhere in the chain silently swallows any
  ``inject_context`` in the same emit regardless of priority.
- Also registers on ``provider:resolve`` to learn the resolved model, since
  ``model`` is not present on ``provider:request``.
- Doses at most once per session. Cue text is untrusted input read from a
  file on disk and is validated before it is ever injected.
- Cue text is never blended into a tool result (no
  ``append_to_last_tool_result``): doing so forges data provenance and is
  structurally identical to prompt injection.
- Fails open unconditionally: any exception, timeout, or malformed ledger
  results in ``continue`` and a logged warning. A ledger problem must never
  cost the user a session.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml
from amplifier_core import HookResult, ModuleCoordinator

__amplifier_module_type__ = "hook"

logger = logging.getLogger(__name__)

# --- Config defaults ---------------------------------------------------

DEFAULT_ROOT = "~/.amplifier/projects/{project}/preceptor"
DEFAULT_EVENT = "provider:request"
DEFAULT_PRIORITY = 20
DEFAULT_RECEIPT = True
DEFAULT_CHANNEL_SEPARATED = True
DEFAULT_READ_TIMEOUT_S = 2.0
DEFAULT_MAX_ACTIVE_CUES = 8
DEFAULT_MAX_CUE_CHARS = 200

# Cue text is untrusted input read from a file on disk that ends up injected
# into a live session. Case-insensitive substrings that indicate a tool
# invocation, privilege-escalation, or instruction-override attempt. A cue
# matching any of these is skipped rather than dosed.
_UNSAFE_PATTERNS: tuple[str, ...] = (
    "bash",
    "<tool",
    "`",
    "approve",
    "permission",
    "sudo",
    "rm -rf",
    "ignore previous",
    "disregard",
    "system prompt",
)

_DOSED_AT = "session-start"


async def mount(
    coordinator: ModuleCoordinator, config: dict[str, Any] | None = None
) -> None:
    config = config or {}

    root_template = str(config.get("root", DEFAULT_ROOT))
    configured_domain = config.get("domain")
    event = str(config.get("event", DEFAULT_EVENT))
    priority = config.get("priority", DEFAULT_PRIORITY)
    receipt = bool(config.get("receipt", DEFAULT_RECEIPT))
    channel_separated = bool(config.get("channel_separated", DEFAULT_CHANNEL_SEPARATED))
    read_timeout_s = float(config.get("read_timeout_s", DEFAULT_READ_TIMEOUT_S))
    max_active_cues = int(config.get("max_active_cues", DEFAULT_MAX_ACTIVE_CUES))
    max_cue_chars = int(config.get("max_cue_chars", DEFAULT_MAX_CUE_CHARS))

    # Per-mount (i.e. per-session) state. A session only ever gets one dose.
    dosed_sessions: set[str] = set()
    session_models: dict[str, tuple[str, str]] = {}

    async def on_provider_resolve(_event: str, data: dict[str, Any]) -> HookResult:
        """Cache (provider, model) per session. `model` only appears here."""
        try:
            session_id = data.get("session_id")
            provider = data.get("provider")
            model = data.get("model")
            if session_id and provider and model:
                session_models[str(session_id)] = (str(provider), str(model))
        except Exception:
            logger.warning(
                "preceptor-cue-injector: provider:resolve caching failed",
                exc_info=True,
            )
        return HookResult(action="continue")

    async def on_provider_request(_event: str, data: dict[str, Any]) -> HookResult:
        """Dose cues once per session. Fails open on any problem."""
        try:
            session_id = data.get("session_id")
            if not session_id or session_id in dosed_sessions:
                return HookResult(action="continue")

            # One shot: mark immediately so this session never gets a second
            # attempt, regardless of what happens below.
            dosed_sessions.add(session_id)

            model_info = session_models.get(session_id)
            if model_info is None:
                # Never guess a model. No provider:resolve seen yet -> dose nothing.
                return HookResult(action="continue")
            provider, model = model_info

            root = _resolve_root(root_template, coordinator)
            domain = _resolve_domain(configured_domain, coordinator)

            manifest_path = root / "manifests" / f"{session_id}.json"
            if manifest_path.exists():
                # Already dosed (e.g. a resumed session) -- never mutate.
                return HookResult(action="continue")

            ledger_path = root / "ledger" / provider / model / f"{domain}.yaml"
            if not ledger_path.exists():
                return HookResult(action="continue")

            started = time.monotonic()
            raw_text = ledger_path.read_text(encoding="utf-8")
            if time.monotonic() - started > read_timeout_s:
                logger.warning(
                    "preceptor-cue-injector: ledger read exceeded %.1fs budget "
                    "for %s; dosing nothing",
                    read_timeout_s,
                    ledger_path,
                )
                return HookResult(action="continue")

            ledger_data = yaml.safe_load(raw_text)
            if not isinstance(ledger_data, dict):
                return HookResult(action="continue")

            cues = ledger_data.get("cues")
            if not isinstance(cues, list):
                return HookResult(action="continue")

            selected = _select_cues(cues, max_active_cues, max_cue_chars)
            if not selected:
                return HookResult(action="continue")

            ledger_version = ledger_data.get("version", 0)
            _write_manifest(
                root, session_id, ledger_version, provider, model, domain, selected
            )

            injection = _build_injection(selected, channel_separated)
            receipt_line = _build_receipt(selected, model, domain) if receipt else None

            return HookResult(
                action="inject_context",
                context_injection=injection,
                context_injection_role="system",
                ephemeral=True,
                suppress_output=True,
                user_message=receipt_line,
                user_message_level="info",
                user_message_source="preceptor",
            )
        except Exception:
            logger.warning(
                "preceptor-cue-injector: dosing failed; failing open", exc_info=True
            )
            return HookResult(action="continue")

    coordinator.hooks.register(
        "provider:resolve",
        on_provider_resolve,
        priority=0,
        name="preceptor-cue-injector-resolve",
    )
    coordinator.hooks.register(
        event,
        on_provider_request,
        priority=priority,
        name="preceptor-cue-injector",
    )


# --- Cue selection and validation ---------------------------------------


def _select_cues(
    cues: list[Any], max_active_cues: int, max_cue_chars: int
) -> list[dict[str, str]]:
    """Select active cues, sorted deterministically, validated, and capped."""
    active = [c for c in cues if isinstance(c, dict) and c.get("status") == "active"]
    active.sort(key=lambda c: str(c.get("id", "")))

    selected: list[dict[str, str]] = []
    for cue in active:
        if len(selected) >= max_active_cues:
            break
        cue_id = cue.get("id")
        text = cue.get("text")
        if not isinstance(cue_id, str) or not cue_id:
            continue
        if not isinstance(text, str) or not _is_safe_cue_text(text, max_cue_chars):
            logger.warning(
                "preceptor-cue-injector: skipping invalid cue %r (untrusted "
                "ledger content failed validation)",
                cue_id,
            )
            continue
        selected.append({"id": cue_id, "text": text})
    return selected


def _is_safe_cue_text(text: Any, max_cue_chars: int) -> bool:
    """Cue text is untrusted input read from a file on disk. Validate it."""
    if not isinstance(text, str) or not text:
        return False
    if len(text) > max_cue_chars:
        return False
    if "</" in text:
        # Would close our wrapper element early.
        return False
    lowered = text.lower()
    return not any(pattern in lowered for pattern in _UNSAFE_PATTERNS)


# --- Injection and receipt formatting -----------------------------------


def _build_injection(selected: list[dict[str, str]], channel_separated: bool) -> str:
    body = "\n".join(f"[cue:{cue['id']}] {cue['text']}" for cue in selected)
    if not channel_separated:
        return body
    return (
        '<preceptor-cues source="preceptor" note="evidence-backed coaching, '
        "subject to revision; the user's explicit instruction always wins\">\n"
        f"{body}\n"
        "</preceptor-cues>"
    )


def _build_receipt(selected: list[dict[str, str]], model: str, domain: str) -> str:
    ids_str = ", ".join(cue["id"] for cue in selected)
    return (
        f"preceptor: {len(selected)} cue(s) active [{ids_str}] \u00b7 "
        f"{model}/{domain} \u00b7 `preceptor cues`"
    )


# --- Manifest (immutable provenance record) -----------------------------


def _write_manifest(
    root: Path,
    session_id: str,
    ledger_version: Any,
    provider: str,
    model: str,
    domain: str,
    selected: list[dict[str, str]],
) -> None:
    """Write the dosing manifest once. Never mutate. Never blocks injection."""
    try:
        manifest_dir = root / "manifests"
        manifest_path = manifest_dir / f"{session_id}.json"
        if manifest_path.exists():
            return
        manifest_dir.mkdir(parents=True, exist_ok=True)
        manifest = {
            "v": 1,
            "session": session_id,
            "ts": datetime.now(timezone.utc).isoformat(),
            "ledger_version": ledger_version,
            "provider": provider,
            "model": model,
            "domain": domain,
            "cues": [
                {
                    "id": cue["id"],
                    "text": cue["text"],
                    "sha256": hashlib.sha256(cue["text"].encode("utf-8")).hexdigest(),
                    "dosed_at": _DOSED_AT,
                }
                for cue in selected
            ],
        }
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    except OSError:
        logger.warning(
            "preceptor-cue-injector: failed to write manifest for session %s",
            session_id,
            exc_info=True,
        )


# --- Root / domain resolution -------------------------------------------


def _project_slug(coordinator: Any) -> str:
    """Derive the `{project}` slug from the session working directory.

    THIS FUNCTION IS DUPLICATED VERBATIM IN THREE MODULES and must stay
    byte-identical in all of them:

        modules/hooks-cue-injector/.../__init__.py         (here)
        modules/tool-preceptor/.../__init__.py
        modules/hooks-trajectory-observer/.../__init__.py

    The duplication is deliberate -- AGENTS.md requires flat, independent
    modules with no cross-imports -- so the agreement is enforced by
    `tests/test_project_slug_agreement.py` at the repo root, which loads all
    three and asserts they return the same slug for the same input. Change
    one, change all three, or that test fails.

    WHY IT MATTERS: all three resolve `{project}` in
    `~/.amplifier/projects/{project}/preceptor` and must land in the SAME
    directory -- the observer writes records there, the tool reads and
    deletes them, and this module reads the ledger and writes the per-session
    dosing manifest. They disagreed THREE ways for `/root/project`:

        tool-preceptor  '-root-project'
        cue-injector    'root-project'    <- this function, stripped the dash
        observer        'project'

    The trailing `.strip("-")` here looked like tidying and was the whole
    divergence from the tool: it made this module the only one whose
    manifests landed outside the tree `preceptor why <session_id>` reads.

    WHY THE DASHED FORM, UNSTRIPPED:

      1. Amplifier core already uses it. `/root/.amplifier/projects/
         -root-project/` exists in a live container as core's own session
         directory -- leading dash included, which is why stripping it was
         wrong rather than merely different.
      2. `Path(working_dir).name` (what the observer used) COLLIDES:
         `/home/alice/project` and `/home/bob/project` both yield `project`.
    """
    working_dir = None
    try:
        working_dir = coordinator.get_capability("session.working_dir")
    except Exception:
        logger.debug(
            "preceptor-cue-injector: could not read session.working_dir capability",
            exc_info=True,
        )
    if not working_dir:
        return "default"
    slug = str(working_dir).replace("\\", "-").replace("/", "-").replace(":", "")
    return slug or "default"


def _resolve_root(root_template: str, coordinator: Any) -> Path:
    raw = root_template
    if "{project}" in raw:
        raw = raw.replace("{project}", _project_slug(coordinator))
    return Path(raw).expanduser()


def _resolve_domain(configured_domain: Any, coordinator: Any) -> str:
    if isinstance(configured_domain, str) and configured_domain:
        return configured_domain
    working_dir = None
    try:
        working_dir = coordinator.get_capability("session.working_dir")
    except Exception:
        logger.debug(
            "preceptor-cue-injector: could not read session.working_dir capability",
            exc_info=True,
        )
    if working_dir:
        name = Path(str(working_dir)).name
        if name:
            return name
    return "default"
