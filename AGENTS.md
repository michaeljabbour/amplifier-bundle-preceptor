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
  paths there, never git URLs, so forks and local dev work.
- **Agent frontmatter is the exception and it must use a git URL.** Relative sources in
  `agents/*.md` resolve against neither the repo root nor the agent's own directory. Verified
  in a Digital Twin: `./modules/tool-preceptor` resolved to
  `amplifier-bundle-wayfinder/behaviors/modules/tool-preceptor` — inside an unrelated sibling
  bundle — and the session refused to start under strict mode. Do not "simplify" these back to
  a relative path.
- **Consent and other user-facing switches are bundle-composition overrides, not
  `settings.yaml` stanzas.** The settings form was documented, shipped, and proven inert in a
  Digital Twin: zero records, exit 0, no error. If you add a switch, prove it end to end in a
  DTU before documenting it.
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

## Known install blocker: cryptography on aarch64

`cryptography==50.0.1`'s wheel SIGILLs (exit 132, empty stderr) on Apple Silicon during
`tool-mcp` import at session init -- a transitive dependency of the `amplifier` CLI itself,
nothing this repo declares or can pin in a module's own `pyproject.toml`. None of our three
modules import `cryptography` or `mcp` at all; inventing a fake dependency edge to hang a pin
on would be dishonest metadata, the same reason `amplifier-core` stays a peer dependency
rather than a real one. Setting `PYTHONFAULTHANDLER=1` before reproducing surfaces a
traceback rooted in `cryptography/exceptions.py`, confirming the crash is the C extension,
not this bundle.

**Workaround, everywhere this repo provisions an environment:**
`uv tool install -vv git+https://github.com/microsoft/amplifier --with "cryptography==45.0.7"`

This was fixed once already for `bench/dtu_run.py`'s own trial containers (commit 5104c9d)
and did not propagate to `bench/arms/*/install.yaml`, which provision the calibration-loop
arms the same way -- both are now pinned. If you add a new install script that runs
`uv tool install ... amplifier` on aarch64, carry the pin forward.

## Before you commit

```bash
# per module
uv run --no-project --with pytest --with pytest-asyncio --with pyyaml pytest tests/
```

Plus `python_check` clean on every changed module. Then ask whether the change added
always-on context — and if it did, whether it earns its tokens.
