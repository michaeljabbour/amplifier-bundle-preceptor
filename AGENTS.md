# Working in amplifier-bundle-preceptor

This bundle's subject is the discipline of removing instructions on evidence. It is
embarrassing when the repo itself violates that discipline, so a few rules are load-bearing.

## The rules that are not negotiable

**Removal carries the burden of proof; addition does not.** Applies to cues, to context files,
and to code in this repo. Do not delete something because it looks unused — show that removing
it changes nothing.

**Never write to the ledger outside `tool-preceptor`.** The schema, the counters, the
fingerprints, and the autonomy lock live there. A filesystem write to a ledger YAML bypasses
every gate this bundle exists to enforce.

**The observer records structure, never content.** No message text, no file contents, no error
bodies, no free-text field. If a change would put any of those on disk, it is wrong regardless
of how useful it would be. See `docs/CONSENT.md`.

**`promote()` and `retire()` must stay mutually exclusive.** There is a property test
enumerating the evidence space. If you change either predicate, that test is the gate.

**Cue text is untrusted input.** It is read from a file and injected into a live session.
Validate on write and on read. Never blend it into a tool result — that forges data provenance
and is structurally identical to prompt injection.

## Layout

| Path | Rule |
|---|---|
| `bundle.md` | Thin. Foundation plus this bundle's own behavior. Nothing else. |
| `behaviors/*.yaml` | `preceptor.yaml` **includes** `preceptor-observer.yaml`. Compose, never duplicate. |
| `bundles/observe-only.yaml` | The adoption path's entry point. A behavior is inert until a bundle includes it. |
| `context/*.md` | Always-on. Under 500 tokens each — that policy is the whole point of this bundle applied to itself. |
| `context/methodology/*.md` | Heavy. `@mention`ed inside agent bodies only, so they cost tokens only when an agent spawns. |
| `modules/*/` | Flat layout, no `src/`. One `pyproject.toml` per module. No root `pyproject.toml`. |
| `docs/theory/` | The theory and its review. Not loaded by the bundle. |
| `docs/diagrams/` | `.dot` sources are the truth; `.svg` are generated. Regenerate, never hand-edit. Keep labels short — width is what kills README-scale legibility, and there is a check for it in `make diagrams`. |

## Module conventions

- `source: ../modules/<name>` from a behavior; `./modules/<name>` from `bundle.md`. Relative
  paths, never git URLs, so forks and local dev work.
- `amplifier-core` is a **peer dependency**. It must not appear in `[project.dependencies]` —
  it is not on PyPI. Put it in `[dependency-groups] dev`.
- Every `mount()` must register something. A `mount()` that returns `None` and registers
  nothing fails `protocol_compliance` on every session load, not eventually.
- `__amplifier_module_type__` at module scope: `"hook"` or `"tool"`.
- **Fail open, always.** Every hook handler returns `HookResult(action="continue")` on every
  path including the error path. A failure in this bundle must never cost the user a session.

## Verified event-surface facts

Learned the hard way; do not re-derive them.

- `tool:post` carries **`tool_name`**, not `tool`. A shipping ecosystem module reads `tool`
  and has therefore been silently broken since it was written.
- `session_id` and `parent_id` are merged into **every** event payload by the kernel. Read
  them; do not query.
- `provider` is on `provider:*` payloads. **`model` is only on `provider:resolve`.** Cache it.
- Hook handlers run **sequentially and in-band**. Per-event disk I/O is latency on every tool
  call. Buffer, then flush.
- **Flush in `register_cleanup()`, not a `session:end` handler.** On the PyO3 path, cleanups
  run *before* `session:end` is emitted, and that emit is best-effort. `session:end` is not
  guaranteed on abnormal termination at all.
- Inject on `provider:request` (priority 20), never `tool:pre`. Precedence is
  `deny > ask_user > inject_context > modify > continue`, and an `ask_user` from the approval
  hook swallows an `inject_context` in the same emit **regardless of priority**.
- Event payload keys are untyped dict literals with no schema and no tests behind them. Use
  `.get()`. Never index.

## Before you commit

```bash
# per module
uv run --no-project --with pytest --with pytest-asyncio --with pyyaml pytest tests/
```

Plus `python_check` clean on every changed module. Then ask whether the change added
always-on context — and if it did, whether it earns its tokens.
