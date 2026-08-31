# Consent and data

Preceptor watches how you work. Read this before enabling it.

## Default: off

`enabled: false` ships as the default in `behaviors/preceptor-observer.yaml`. With it off,
`mount()` registers nothing at all — no handlers, no files, no overhead. Verified empirically
in a Digital Twin: a full session with tool calls produced zero files anywhere on the
filesystem.

Turning it on is a deliberate act — you choose a different bundle:

```bash
amplifier run --bundle 'git+https://github.com/michaeljabbour/amplifier-bundle-preceptor@main#subdirectory=bundles/observe-on.yaml'
```

**There is no settings-file stanza, on purpose.** An earlier draft documented one
(`modules.hooks[].config.enabled` in `~/.amplifier/settings.yaml`). A Digital Twin run proved
it inert: the session ran, exit code 0, and zero observation records were written — no error,
no warning, no way for a user to tell whether they had opted in or not. A consent control that
silently fails open-or-closed is worse than no control, so it was removed rather than
documented with a caveat.

## What is recorded

**Structure only.** One JSON object per event:

| Field | Example | Note |
|---|---|---|
| `event` | `tool:post` | Which lifecycle event |
| `tool_name` | `edit_file` | Which tool ran |
| `tool_input_sha256` | `9f2a…` | A **hash**, never the input |
| `ok` | `true` | Success flag |
| `iteration`, `parallel_group` | `14`, `null` | Position in the run |
| `session`, `parent` | `5f2c…`, `null` | Identity and lineage |
| `provider`, `model` | `anthropic`, `claude-opus-5` | Which model produced the form |
| `cue_ids_dosed` | `["cue-017"]` | Correlation key |

The hash exists for one reason: an exact-duplicate call is the signature of a retry loop, and
detecting it needs equality, not content.

## What is never recorded

- Message text — yours or the model's
- File contents, diffs, or paths beyond the tool name
- Tool inputs or outputs
- Error message bodies
- Reasoning or thinking content
- **Any free-text field at all**

The original design had a `detail` field holding a prose summary of what happened. It was
removed. A free-text field derived from session content will eventually contain business
logic, customer data, and a pasted credential, and the store would inherit the sensitivity of
the most sensitive session with none of the handling.

There is a consequence worth stating plainly: naming a signal (`arbitration`, `retry-loop`)
is a judgment, and it now happens in `preceptor:form-analyst` reading the records — not in the
hook. That is better anyway. A taxonomy compiled into a module can only change with a module
release, and this one will change weekly.

## Where it lives, and for how long

`~/.amplifier/projects/{project}/preceptor/observations/<session_id>.jsonl` — local, never
transmitted. Deleted after `retention_days` (default 90). The derived ledger is not sensitive
and persists.

`.gitignore` excludes `observations/` and `manifests/`. Do not commit them.

## Your controls

| Want | Do |
|---|---|
| See what exists | `preceptor status` |
| Read your own records | `preceptor observations --mine` |
| Stop recording | compose `observe-only`; unset `PRECEPTOR_ENABLED` |
| Delete records | `preceptor forget --since <date>` |

`forget` is real revocation, not a filter: it removes the records **and** marks any cue whose
entire `origin` set was deleted as `unsupported`, which blocks it from ever being promoted. A
cue must not outlive the evidence that justified it.

## If you share a ledger with a team

Open question, and the two options are not variants of one design.

| | Per-user, local | Per-project, shared |
|---|---|---|
| Evidence quality | Thin, slow to converge | Strong, fast |
| Consent model | Implicit is acceptable | **Explicit and revocable, required** |
| Failure mode | Underpowered | **Performance-adjacent artifact** |

In a small team, a session id plus commit timing deanonymizes trivially. A shared ledger then
becomes a record of whose sessions needed the most correcting — and even if nobody intends to
read it that way, its *availability* changes behavior. People route risky work outside the
observed harness, which harms them and poisons the evidence at the same time.

**If you share:** share the derived ledger, keep the raw observations local and pseudonymous,
and never record which team member produced an observation.

**Watch `observed-session share`** — the fraction of a consenting developer's work done inside
the observed harness. A falling share is the signature of a chilling effect. Treat it as a
defect, not as low engagement.

## One more thing being recorded

Your own repeated corrections — you telling the agent the same thing twice — are a form signal
and the loop reads them. That is defensible as a signal. It is not defensible as an unconsented
one, which is why it is written down here.
