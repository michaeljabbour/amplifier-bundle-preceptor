# hooks-cue-injector

Doses evidence-backed cues from the preceptor ledger into a session, once,
with a human-visible receipt and an immutable provenance record.

## What it doses

At most once per session -- on the first turn -- this hook reads the
per-`(provider, model, domain)` credential ledger at
`<root>/ledger/<provider>/<model>/<domain>.yaml`, selects the cues whose
`status` is `active` (never `proposed`, `shadowed`, or `faded`), sorts them
deterministically by id, caps the count at `max_active_cues`, and injects
each as a tagged line: `[cue:<id>] <text>`. A cue is coaching subject to
revision, not doctrine -- if it conflicts with the user's explicit
instruction, the user wins.

## Why `provider:request`

`provider:request` fires *before* messages are fetched, specifically so
hooks can inject context, and it is uncontested in the default hook stack.
`tool:pre` is gated by `hooks-approval`, and hook precedence is
`deny > ask_user > inject_context > modify > continue` -- an `ask_user`
result anywhere in that emit silently swallows any `inject_context` in the
same emit *regardless of priority*. Registering on `provider:request`
instead sidesteps that entirely.

Because `model` is only present on the separate `provider:resolve` event,
this module also registers a lightweight `provider:resolve` handler purely
to learn `(provider, model)` before the first `provider:request` arrives.
If no model is known yet, it doses nothing rather than guessing.

## The receipt

Dosing is never silent. Every successful dose emits a one-line
human-visible receipt via `user_message`, e.g.:

```
preceptor: 3 cue(s) active [cue-017, cue-022, cue-031] · claude-opus-5/python-implementation · `preceptor cues`
```

## The manifest

Every successful dose writes `<root>/manifests/<session_id>.json` once, and
never mutates it afterward (checked both in-memory and on disk, so this
holds even across a resumed session in a fresh process). It records the
verbatim cue text, a `sha256` of that text, and the ledger's `version` at
dose time. This is what answers "why did it do that last Tuesday?" after a
cue has since been retired from the live ledger -- reading the live ledger
at that point would give the wrong answer, because the ledger has moved on.
A manifest write failure is logged and never blocks the injection itself.

## Cue text is untrusted input

The ledger is a file on disk that ends up injected into a live session.
Every cue is validated before it is dosed; a cue that fails validation is
skipped and logged, never raised:

- length must be within `max_cue_chars`
- rejected (case-insensitive) if it contains tool-invocation or
  privilege-escalation patterns such as `bash`, `<tool`, a backtick,
  `approve`, `permission`, `sudo`, `rm -rf`, `ignore previous`,
  `disregard`, or `system prompt`
- rejected if it contains `</`, which would close the injection's wrapper
  element early

Cue text is **never** blended into a tool result (no
`append_to_last_tool_result`). Doing so would forge data provenance and is
structurally identical to prompt injection -- the cue is always delivered
in its own labelled block (`channel_separated`, default on), separate from
any tool output.

## Fails open, unconditionally

Any exception, any ledger read that exceeds `read_timeout_s`, or any
malformed YAML results in `continue` and a logged warning -- never an
unhandled error. A ledger problem must never cost the user a session.

## Config

| key | default | meaning |
|---|---|---|
| `root` | `~/.amplifier/projects/{project}/preceptor` | Base dir. `{project}` is substituted from the session's working directory; `~` is expanded. |
| `domain` | (working-dir basename, else `default`) | Overrides automatic domain detection. |
| `event` | `provider:request` | Event the main dosing handler registers on. |
| `priority` | `20` | Registration priority for the dosing handler. |
| `receipt` | `true` | Emit the human-visible one-line receipt. |
| `channel_separated` | `true` | Wrap cue text in its own labelled `<preceptor-cues>` block. |
| `read_timeout_s` | `2.0` | Ledger read budget; exceeding it doses nothing. |
| `max_active_cues` | `8` | Hard ceiling on cues dosed per session. |
| `max_cue_chars` | `200` | Per-cue text length ceiling. |
