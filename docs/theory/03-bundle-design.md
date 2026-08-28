# amplifier-bundle-preceptor: Design

*Draft, August 28, 2026*

The preceptor as an Amplifier bundle: an observer hook that reads session trajectories for form, a credential ledger keyed by provider, model, and domain, a cue injector that doses minimal context from the active credential, and offline recipes that assess new models, propose cues, and fade them with eval evidence. Thin bundle on `foundation`, value shipped as a behavior, per the ecosystem's recommended pattern. Clinical vocabulary is canonical throughout: the ledger grants **privileges**, assess-model administers **boards**, review-form is **chart review**, and a fade is the **entrustment scale** stepping down a level of supervision.

## Repository shape

```
amplifier-bundle-preceptor/
├── bundle.md                     # thin: foundation + own behavior
├── behaviors/
│   ├── preceptor.yaml              # full loop: hooks + tool + agents + awareness
│   └── preceptor-observe-only.yaml # adoption path: observer hook alone
├── agents/
│   ├── form-analyst.md           # deep read of a single session log
│   ├── credentialer.md           # ledger writes, schema enforcement
│   ├── skeptic.md                # adversarial check on proposed cues and fades
│   └── assessor.md               # runs probes, grades against rubrics
├── context/
│   ├── awareness.md              # under 500 tokens, always-on
│   └── methodology/              # heavy docs, @mentioned in agent bodies only
├── modules/
│   ├── hooks-trajectory-observer/
│   ├── hooks-cue-injector/
│   └── tool-credential/
├── recipes/
│   ├── assess-model.yaml         # boards: baseline a new model or domain
│   ├── review-form.yaml          # batch preceptor pass over recent sessions
│   ├── fade-check.yaml           # eval-gated cue removal
│   └── preceptor-doctor.yaml       # audit the composed bundle stack itself
├── probes/                       # canary tasks with executable rubrics
└── docs/
```

## The eyes: hooks-trajectory-observer

A hook module that subscribes to session lifecycle events and captures form signals per turn: tool-call sequences, retry loops, repeated reads of the same file, error-recovery paths, and arbitration moments where output wrestles with conflicting instructions. It appends structured observation records to the ledger and returns continue on every event. It never gates, never modifies, never adds latency to the model's path.

Composition follows the policy-behavior pattern: the app composes it, and the hook checks `parent_id` so root sessions and subagent sessions get tagged with lineage rather than filtered out, since delegation form is form too. If the current hook surface in `amplifier-core` proves too coarse for per-turn capture, the fallback is a log-tailing module reading the same session logs the log viewer streams, which trades immediacy for zero contract risk.

## The ledger

Per-model, per-domain credential documents holding assessment history, active cues with evidence links and counters, and a faded list recording the eval run that licensed each removal. Full schema and lifecycle in `04-credential-schema.md`. Observations arrive from the hook; cue and fade writes go through the credentialer agent so every mutation carries provenance.

`tool-credential` exposes the ledger with an expressive schema rather than examples, applying the interfaces-over-examples shift to our own tool: `read_profile(provider, model, domain)`, `propose_cue(...)` requiring evidence session ids, `fade_cue(...)` requiring an eval run id, `log_assessment(...)`. The parameter requirements teach the discipline. Module config (ledger path, retention) arrives through app-level settings injection; anything secret stays in environment variables.

## The mouth: hooks-cue-injector

At session start the injector reads the active credential for the current provider, model, and detected domain, and doses only live cues, each tagged `[cue:id]` so the model reads them as coaching subject to revision rather than doctrine to obey forever. The tag also lets the observer correlate cue presence with behavior, which feeds the counters that drive fading.

Point-of-action dosing rides the tool-result channel: the injector annotates the relevant tool output with the applicable cue, mirroring how Anthropic delivers reminders adjacent to the action they govern instead of at the top of the prompt. Provider switching comes free: `amplifier provider use` changes which credential the injector reads, so a session on GPT-5.5 receives scaffolds a session on Opus 5 shed months ago.

**Open contract question:** whether hooks in the current `amplifier-core` contract can contribute context mid-session or only gate. If gating only, dosing degrades to session-start assembly, still per-model and still fading, and the tool-result annotation waits on a contract extension.

## Boards: assess-model

On first contact with an unknown provider and model pair, or on demand, the recipe runs canary probes from `probes/` and the assessor grades results against executable rubrics: test suites and reference implementations rather than prose descriptions, per the rich-references shift. Output is the initial credential. Cold start defaults to the highest-scaffold profile known for that provider family, then fades from evidence, which is the safe direction to be wrong in.

## Chart review: review-form and fade-check

`review-form.yaml` fans out over recent sessions and accumulated observations, synthesizes candidate cues and candidate fades, and hands both to the skeptic for adversarial verification. A cue survives if it would have prevented a mistake that actually occurred in the evidence. A fade survives if the cue's violation count sits at zero across enough observed opportunities. `fade-check.yaml` then runs the domain probes with and without the cue in isolated sessions; a flat result licenses deletion, and the credentialer records the fade with its evidence. Together these turn Anthropic's one-time 80% cut into a standing mechanism and their session-mining suggestion into a continuous native loop.

## Routing learnings to the right construct

The preceptor's second judgment call, after whether a learning is real, is where it belongs. Model-specific scaffolds go to the ledger and fade on schedule. Codebase gotchas go to project context files, since they hold for any model. Repeatable procedures become skills. User preferences belong to memory, and the preceptor leaves them there. Auto-memory runs untouched: observations are telemetry rather than memories, though churn in memory files (the user correcting the same thing again) is itself a form signal the observer reads.

`preceptor-doctor.yaml` closes the loop on the context itself: it audits the composed bundle stack for oversized `context.include` entries and clashing instructions across composed bundles, then proposes deletions gated by probes rather than judgment calls. The ecosystem's May 2026 bloat migration would have been a scheduled run instead of a rescue.

## Progressive disclosure compliance

The behavior's `context.include` carries only `awareness.md`, under the 500-token ceiling: the system exists, cues carry `[cue:id]` tags and may fade, credentials live at a stated path, delegate to preceptor agents for anything heavy. Methodology documents load as `@mentions` inside agent bodies, the context-sink pattern, so they cost tokens only when a preceptor agent spawns. Ledger write tools scope to preceptor agents through inline agent definitions plus `spawn.exclude_tools`, which is the native equivalent of deferred tool loading: the main session never carries what only the preceptor uses.

## Adoption path

`preceptor-observe-only.yaml` ships the observer with nothing else. Teams run it for two weeks, read the observation ledger, and decide whether the form notes justify the rest. Watching before coaching applies to the bundle's own rollout.

## Open questions

1. Event granularity in the current hook surface: per-tool-call and per-provider-turn events, or session-level only. Determines observer versus log-tailer.
2. Mid-session context contribution in the hook contract, per above.
3. Domain detection: start coarse, project plus a task-type classification at session start, and resist cleverness until the ledger shows it matters.
4. Eval isolation for fade-check: recipes spawning fresh sessions should suffice; confirm no cross-contamination through shared project state.
5. Ledger location and multi-user semantics: per-user under `~/.amplifier`, or per-project and shared, with the credential as a reviewable artifact in the repo.

## Next steps

Scaffold the repo: `bundle.md`, `behaviors/preceptor.yaml`, the three module stubs honoring the `mount()` iron law, the credential schema as code, and two starter probes with executable rubrics. Then take the two contract questions to `amplifier-core`.
