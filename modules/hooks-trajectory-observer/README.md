# hooks-trajectory-observer

Records raw structural trajectory form off the model's path.

This hook module appends a one-line JSON record for every observed lifecycle
event -- which event fired, for which tool, with what coarse outcome -- to a
per-session JSONL file. It exists to answer *"what shape did this session
take?"* without ever recording *what the session was about*.

## Consent gate

**Off by default.** Unless `enabled: true` is explicitly set in config, `mount()`
registers no event handlers at all and returns immediately after a single log
line. There is no partial-observation mode -- it is either fully off or fully
on. See your bundle's `docs/CONSENT.md` for the policy this implements; set
`enabled` in `~/.amplifier/settings.yaml`, not in the bundle itself.

## What it records

One JSON object per line, per observed event:

```json
{"v":1,"id":"obs-14","ts":"2026-08-28T12:00:00+00:00","session":"sess-1",
 "parent":null,"provider":"anthropic","model":"claude-opus-5",
 "event":"tool:post","tool_name":"edit_file",
 "tool_input_sha256":"9f2a...","ok":true,"iteration":14,
 "parallel_group":null,"cue_ids_dosed":[]}
```

| Field | Meaning |
|---|---|
| `v` | Schema version (currently `1`) |
| `id` | Monotonic per-session record ID (`obs-<n>`) |
| `ts` | UTC ISO-8601 timestamp of the record |
| `session` / `parent` | Session and parent session IDs |
| `provider` / `model` | Cached from the last `provider:resolve` event, stamped onto every subsequent record |
| `event` | The observed event name |
| `tool_name` | From `tool_name` in the event payload (never the wrong `tool` key) |
| `tool_input_sha256` | SHA-256 hash of the tool input -- lets an exact-duplicate call be detected without carrying content |
| `ok` | Coarse boolean outcome, derived from the event/result, never a message |
| `iteration` | Loop iteration number, when the event carries one |
| `parallel_group` | Parallel tool-call group ID, when applicable |
| `cue_ids_dosed` | IDs of any preceptor cues active for this session (read from the sibling dosing manifest, if present). The manifest is read on the first event and, if absent then, once more on the first `provider:request` (where the injector writes it), so in a new session only records before that request carry `[]` |

Observed events: `tool:pre`, `tool:post`, `tool:error`, `provider:request`,
`provider:response`, `provider:retry`, `provider:error`,
`provider:tool_sequence_repaired`, `provider:resolve`, `session:fork`,
`execution:start`, `execution:end`, `cancel:requested`.

## What it explicitly does NOT record

- **No message content.** No prompts, no responses, no file contents.
- **No tool inputs or outputs.** Only a SHA-256 hash of the input.
- **No error messages.** `ok` is a bare boolean; there is no `detail` or
  message field anywhere in the schema.
- **No signal classification.** Whether a pattern looks like an
  "arbitration," a "retry-loop," or anything else is deliberately left to an
  agent reading these records later -- that judgment must stay changeable
  without a module release.

This module never gates, blocks, modifies event data, injects context, or
shows a user message. Every handler returns `HookResult(action="continue")`
on every path, including the error path.

## Where files land

```
<root>/observations/<session_id>.jsonl   # the trajectory records
<root>/payload-shapes.json               # one-time payload-key discovery (optional)
```

`<root>` defaults to `~/.amplifier/projects/{project}/preceptor`, where
`{project}` and `{session_id}` are `str.format` placeholders resolved at
mount time from the session's working directory and session ID.

## Configuration

| Key | Default | Meaning |
|---|---|---|
| `enabled` | `False` | Consent gate. Nothing is recorded until this is `true`. |
| `root` | `~/.amplifier/projects/{project}/preceptor` | Base directory template. |
| `flush_every` | `25` | Buffer size before an opportunistic flush. |
| `retention_days` | `90` | Observation files older than this are deleted once, at mount. |
| `priority` | `200` | Hook registration priority. Runs behind `hooks-logging` (100); an observer should never precede anything. |
| `record_payload_shapes` | `True` | Also write a one-time payload-key discovery dump to `payload-shapes.json`. |

## The retention clock

Once per mount, any file in `observations/*.jsonl` whose modification time is
older than `retention_days` is deleted. This is a best-effort sweep -- a
retention failure is logged and never blocks the session from starting.

## Reliability

Handlers run sequentially and in-band with the rest of the session, so
records are buffered in memory and only written to disk at these points:

- The buffer reaches `flush_every` records. This mid-turn flush is handed
  to a background writer and does **not** block the handler.
- An `execution:end` or `cancel:requested` event fires. The handler blocks
  until everything buffered is on disk, as before.
- The session's registered cleanup callback runs at teardown (this is the
  guaranteed final flush, also blocking -- `session:end` is not relied upon,
  since on the underlying runtime cleanups run *before* `session:end` is
  emitted, and it is not emitted at all on abnormal termination).

Hashing a large `tool_input` also runs on that writer instead of in the
handler. "Large" is a cheap estimate, not a serialization: the lengths of
the input's top-level string values, with **any** nested dict/list/tuple
value counted as 4096 characters, so every input with a nested container
(todo lists, edit arrays) takes the background path; a top-level list counts
as large past 64 items. Inputs under 4096 estimated characters are hashed
inline. `tool:post` reuses the digest computed for the matching `tool:pre`
when it carries the same `tool_call_id` and the same arguments object. The
writer is one shared thread, so jobs run strictly in order and every digest
is the same bytes hashed the same way as before. Trade-off: a background
digest is computed after any queued writer work (unbounded if the writer is
stalled, e.g. on a slow disk) rather than during the event, so an input
mutated in place before the hash job runs would hash its mutated form, and
that digest is then reused for `tool:post`. Measure with
`bench/footprint.py`.

Durability trade-off: records past the `flush_every` threshold are in
flight, not on disk, when the handler returns; a SIGKILL in that window
loses them. The eager points and cleanup still block (capped at 10 s so a
hung disk cannot hang the session), and on normal interpreter exit the
writer drains its queue.

A failure at any point (a bad flush, a malformed payload, a missing
capability) is logged and never raised -- fail-open is absolute. Observation
is a side effect of the session, never something that can cost the user the
session itself.
