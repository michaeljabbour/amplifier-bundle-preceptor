# Privileges: The Credential Schema

*Draft, August 28, 2026*

A credential in Preceptor is what a hospital calls privileges: procedure-specific permission earned from observed, documented competence. Design principles: every entry links to evidence, keys are provider plus model plus domain, documents are versioned and diffable, and the format serializes cleanly so credentials travel across harnesses.

## Observation record

The trajectory observer appends these. Append-only, one file per session or a rolling store, schema-stable so offline recipes can fan out over them.

```yaml
observation:
  id: obs-1198
  session: 5f2c…            # session id, lineage-tagged if subagent
  provider: anthropic
  model: claude-opus-5
  domain: python-implementation
  turn: 14
  signal: arbitration        # arbitration | retry-loop | re-read |
                             # error-recovery | cue-violation | cue-honored
  cue_ref: cue-017           # when the signal concerns a dosed cue
  detail: "output weighed conflicting comment guidance before editing"
  ts: 2026-08-27T19:42:11Z
```

## Credential document

One per provider, model, and domain. The injector reads it at session start; the credentialer agent is the only writer.

```yaml
credential:
  provider: anthropic
  model: claude-opus-5
  domain: python-implementation
  version: 7
  entrustment: indirect      # observe-only | direct | indirect | unsupervised
  assessed:
    - run: probe-run-3
      date: 2026-08-28
      probes: [py-refactor-01, py-testfirst-02]
      result: pass            # rubric outcomes recorded per probe

  cues:
    - id: cue-017
      text: "Run the module's tests before declaring a refactor done."
      status: fading           # proposed | active | fading | faded
      origin: [obs-1141, obs-1198]
      validated: eval-run-91c  # entry gate: probe delta when the cue was introduced
      opportunities: 23        # situations where the cue applied
      violations_recent: 0     # violations across the last N opportunities
      dosed_at: session-start  # session-start | tool-result:<tool>
      decay: 20                # opportunities at zero violations before fade-check

  faded:
    - id: cue-004
      text: "Do not write multi-paragraph docstrings."
      faded: 2026-07-30
      evidence: eval-run-88a   # probe run flat with and without the cue
      origin: [obs-0212]
```

The `entrustment` field summarizes the domain at a glance. It steps down a level as cues fade with probes holding, mirroring supervision levels in clinical training, and it never steps down on judgment alone.

## Cue lifecycle

**Proposed.** The chart review recipe surfaces a candidate from observed corrections. The skeptic verifies it against the evidence: the cue must have prevented a mistake that actually occurred. Survivors enter the credential as proposed. Promotion is itself gated: the injector doses the proposed cue in live sessions, and the credentialer promotes only when the observed behavior changes and the domain probes improve or hold. A cue that changes nothing gets struck before it accretes, and the validation run is recorded on the cue.

**Active.** The injector doses the cue every applicable session. The observer counts opportunities and violations through the `[cue:id]` tag.

**Fading.** Violations hold at zero for the cue's decay window. Fade-check runs the domain probes with and without the cue in isolated sessions. A flat result moves the cue to faded with the eval run recorded; a regression resets the counters and keeps the cue active.

**Faded.** Removed from dosing, retained in the document with evidence. A faded cue can return if the model, the codebase, or the domain shifts and violations reappear, and the record of the earlier fade keeps the return honest.

Only the fade-check gate deletes. Judgment proposes; evidence disposes.

## Portability: credentials over OSP

Observations and credentials should serialize over the Open Session Protocol so form earned in one harness ports to another. A team running Claude Code and Amplifier side by side earns one ledger, and a credential becomes a cross-harness asset rather than a runtime-local cache. The schema above stays deliberately flat for this reason: ids, counters, evidence links, and timestamps, with no runtime-specific structures. The OSP mapping needs one addition, a stable way to reference a session and turn in a foreign harness's log, which belongs in the protocol conversation rather than in this bundle.
