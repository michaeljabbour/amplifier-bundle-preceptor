# The on-disk format

The file format is the interface between the three modules. The observer writes
observations, the injector reads the ledger and writes manifests, the tool reads and writes
everything. No module imports another. **If you change a format here, all three change.**

Everything lives under `root` (default `~/.amplifier/projects/{project}/preceptor`).

```
preceptor/
├── observations/<session_id>.jsonl    # observer, append-only, retention-bound
├── manifests/<session_id>.json        # injector, immutable, content-hashed
├── ledger/<provider>/<model>/<domain>.yaml
├── assessments/<run_id>.json
├── payload-shapes.json                # one-time event-schema discovery dump
└── state.json                         # autonomy lock + trust counters
```

Flat, boring, and free of runtime-specific structures — so this can later be backed by a
graph store or a different harness without rewriting the readers.

## observations/&lt;session_id&gt;.jsonl

One JSON object per line. **Structural only.** No message content, no file contents, no
free text. A bounded `note` field exists for the analyst to attach *derived* commentary; the
observer never writes it.

```json
{
  "v": 1,
  "id": "obs-1198",
  "ts": "2026-08-27T19:42:11Z",
  "session": "5f2c...",
  "parent": null,
  "provider": "anthropic",
  "model": "claude-opus-5",
  "event": "tool:post",
  "tool_name": "edit_file",
  "tool_input_sha256": "9f2a...",
  "ok": true,
  "iteration": 14,
  "parallel_group": null,
  "cue_ids_dosed": ["cue-017"]
}
```

`tool_input_sha256` is a hash, never the input. It is enough to detect the exact-duplicate
call pattern that indicates a retry loop, and it carries no content.

`cue_ids_dosed` is the correlation key. It is what makes a single instruction attributable
inside a trajectory, and therefore what makes cue-level ablation measurable at all.

## manifests/&lt;session_id&gt;.json

Written once at dose time. **Never mutated, never deleted with the cue.** This is what
answers "why did it do that last Tuesday?" after the cue has since been retired — reading
the live ledger would give the wrong answer, because the ledger has moved on.

```json
{
  "v": 1,
  "session": "5f2c...",
  "ts": "2026-08-27T19:11:02Z",
  "ledger_version": 7,
  "provider": "anthropic",
  "model": "claude-opus-5",
  "domain": "python-implementation",
  "cues": [
    {"id": "cue-017", "text": "Run the module's tests before declaring a refactor done.",
     "sha256": "4b1e...", "dosed_at": "session-start"}
  ]
}
```

## ledger/&lt;provider&gt;/&lt;model&gt;/&lt;domain&gt;.yaml

One document per triple. Git-trackable: one commit per mutation, evidence ids in the
message. That is what makes "versioned and diffable" true rather than aspirational, and it
gives diff, blame, revert, and review for free.

```yaml
v: 1
provider: anthropic
model: claude-opus-5
model_fingerprint: "sha256:1c4f..."
domain: python-implementation
environment_fingerprint: "sha256:aa71..."
version: 7
supervision: medium          # DERIVED. Never authored. See "supervision" below.

cues:
  - id: cue-017
    text: "Run the module's tests before declaring a refactor done."
    status: active           # proposed | active | shadowed | faded
    origin_class: observed   # observed | human
    origin: [obs-1141, obs-1198]
    entry_evidence: eval-run-91c    # REQUIRED to reach active
    exit_evidence: null             # REQUIRED to reach faded
    opportunities: 23
    violations_recent: 0
    pinned: false
    dosed_at: session-start
    shadowed_at: null
    created: 2026-07-14T09:00:00Z
```

### Two fingerprints, and why both

`model_fingerprint` — a provider will swap weights behind a stable identifier like
`claude-opus-5`. Without a fingerprint the ledger keeps governing a model that no longer
exists behind that string, silently. On change: every cue returns to `shadowed` for
revalidation.

`environment_fingerprint` — dependency majors plus a hash of the domain's file patterns.
The model is frozen; the *environment* is what moves. A cue retired under one environment
is not evidence about a different one. On change: every `faded` cue under the prior
fingerprint returns to `shadowed`.

Without these, the system learns that a retirement was wrong **by letting the failure
recur on the user**. That is not acceptable as a learning mechanism.

### `supervision` is derived and decorative

It summarizes cue count and status. Nothing may read it to relax an approval gate, widen a
permission, or skip a check. If that ever becomes desirable it requires `signed_by` and
`signed_at` fields and a human signature — because a system that grants itself operational
autonomy under a word borrowed from a domain where a person signs is the single most
dangerous thing in this design.

## state.json

```json
{
  "v": 1,
  "fade_attempts": 47,
  "shadow_restores": 2,
  "false_fade_rate": 0.0426,
  "detector_calibrated": false,
  "detector_precision": null,
  "detector_recall": null,
  "autonomy_unlocked": false
}
```

`false_fade_rate = shadow_restores / fade_attempts` is the system's own trustworthiness
metric, and it is a gate rather than a report. See `cue-lifecycle.md`.
