# Expert Review of the Preceptor Theory

*Compiled August 28, 2026. Review of `01`–`04` by five specialist agents plus synthesis.*

Reviewers: `core:core-expert` (kernel contract), `amplifier:amplifier-expert` (ecosystem
overlap), `foundation:foundation-expert` (bundle conformance), `mj:crusty-old-engineer`
(reliability), `ux-ergonomist:human-agent-designer` (authority and trust).

---

## 1. What the theory is, restated

Stripped of vocabulary, the thesis is one asymmetry:

> Every context system has an ADD mechanism. None has a REMOVE mechanism. So context
> only accretes, and removal happens as periodic manual surgery by whoever gets to it.

Two independent instances of that shape are cited and both hold up: Anthropic cutting 80%
of the Claude Code system prompt with no eval loss, and this ecosystem's own 15–20k
token/session bloat migration. Both were rescues, not mechanisms.

Preceptor proposes to make removal a **standing, evidence-gated function**. Three
commitments, where the ordering is the content: observe before instructing; correct only
from a failure that actually happened; make every correction prove itself twice — once to
enter, and continuously to stay.

The second-order claim: the right amount of scaffolding is model-dependent, a runtime
fronting several model families cannot prune globally, so the record must be per-model —
which places it in the platform layer rather than in any single product.

### The irreducible novel contribution

Per `amplifier-expert`, and confirmed against the ecosystem inventory:

1. **The cue as a first-class lifecycle object with a standing fade obligation.** Nothing
   in the ecosystem treats *an instruction* as an entity with entry evidence, live
   counters, and a scheduled removal proof.
2. **The `[cue:id]` tag as a correlation key.** This is the load-bearing invention. It
   makes an individual instruction attributable inside a trajectory, which is what makes
   cue-level ablation measurable at all.
3. **The closed loop from observed form to instruction mutation.**

Not novel: the observer, the event substrate, the form-signal catalogue, the detached
worker pattern, the ablation arithmetic, the verdict schema, the mid-session injector, the
ledger, eval isolation, per-model resolution. All of those exist.

> The novelty survived the audit because it sits on a *surface* nobody had ablated, not
> because it is a new *mechanism*. Targets are cheap to add; mechanisms are not.

---

## 2. Kernel contract — both open questions are closed

`03-bundle-design.md:80-81` flags two questions for `amplifier-core`. Both are answered by
the shipped contract. **Do not open that conversation.**

### Q1 — Event granularity: available, wider than assumed

43 canonical events (`events.rs:370`). Everything the observer needs:

| Need | Event | Source |
|---|---|---|
| Tool call + result | `tool:pre`, `tool:post`, `tool:error` | `events.rs:97,99,101` |
| Provider turn | `provider:request`, `provider:response`, `provider:retry`, `provider:error` | `events.rs:58-76` |
| Reasoning content | `thinking:delta`, `thinking:final`, `content_block:*` | `events.rs:81-92` |
| Subagent spawn | `session:fork` | `events.rs:37` |
| Session boundaries | `session:start/end/resume`, `execution:start/end`, `orchestrator:complete` | `events.rs:33-46,117-121` |

`parent_id` is merged into **every** event payload automatically via `set_default_fields`
(`session.rs:172-176` + `hooks.rs:189-191`). Lineage is free.

Two bonuses:

- **`provider:tool_sequence_repaired`** (`events.rs:67`) fires when a provider had to repair
  a malformed tool-call sequence the model produced. A pure model-form defect, already
  classified, already named — the highest-signal cue candidate on the surface.
- `delegate:*` events arrive via `collect_contributions("observability.events")`, not
  `ALL_EVENTS`.

**Strike the log-tailing fallback** at `03-bundle-design.md:40`. `events.jsonl` *is produced
by a hook module doing exactly what the observer would do* (`hooks-logging`). Tailing it is
tailing our own output through a middleman.

### Q2 — Mid-session contribution: yes, and the injector already exists

`HookResult` is not gate-only (`models.py:127-320`): `context_injection`,
`context_injection_role`, `ephemeral`, `append_to_last_tool_result`, plus `action="modify"`
to replace a tool result outright.

`hooks-todo-reminder` is the injector, already in production: registers on `tool:post` for
state and `provider:request` for injection, returns
`inject_context / ephemeral / append_to_last_tool_result`.

Three timing facts that will bite:

- `provider:request` fires **before** messages are fetched, explicitly to allow injection
  (`loop-streaming:2892`). That is the dosing point.
- Injections returned from `tool:post` are **deferred one turn** (queued to
  `_pending_ephemeral_injections`, applied at `:2958`). `dosed_at: tool-result:<tool>` must
  record which delivery it means.
- Precedence is `deny > ask_user > inject_context > modify > continue` (`hooks.rs:20`), and
  **priority does not help** (`hooks.rs:256-261`). An `ask_user` anywhere in the chain
  swallows the cue for that emit. Mitigation: register on `provider:request`, which is
  uncontested in the default stack, not `tool:pre`, which `hooks-approval` gates.

Merge semantics (`hooks.rs:425-455`): content joins with `\n\n`; `ephemeral` and
`append_to_last_tool_result` are OR'd across contributors; `context_injection_role` and
`suppress_output` are **first-wins by priority**.

### Correction: "never adds latency" is false as written

`03-bundle-design.md:38` claims the observer never adds latency. Handlers execute
**sequentially and in-band** — `hooks.rs:210` awaits each before the emit returns. A ledger
write on every `tool:post` is synchronous latency on every tool call.

**Correct pattern:** buffer in memory; flush on `execution:end` (bounded loss, off the
per-tool path) and in a `register_cleanup()` callable.

**A real discrepancy to design around.** Two `cleanup()` implementations run `session:end` in
opposite order. Pure-Rust `session.rs:397-414` emits `session:end` then runs cleanup. The
PyO3 path (`bindings/python/src/session.rs:540-546`) runs cleanup *first*, then emits, and
marks the emit **best-effort**. Python modules run on the PyO3 path. Therefore: **flush in
`register_cleanup()`, never in a `session:end` handler.** `session:end` is not guaranteed on
abnormal termination at all — SIGKILL, OOM, or a hard crash lose the buffer.

### Payload keys are unschema'd — verify every one

Event *names* are constants with tests behind them. Event *payload keys* are untyped dict
literals written inline by whichever orchestrator is mounted, with no schema and no test.

Live proof: `hooks-todo-reminder/__init__.py:82` reads `data.get("tool", "")` but the
orchestrator emits `tool_name` (`loop-streaming:3824-3833`). Its `recent_tools` has been
permanently empty and the reminder fires unconditionally.

**Action:** in the first observe-only run, dump observed payload shapes across `ALL_EVENTS`
and treat that dump as the real schema.

---

## 3. Ecosystem overlap — ~85% already exists

`amplifier-expert`'s finding, verified against MODULES.md and the repos.

| Preceptor piece | Existing construct |
|---|---|
| Observation substrate | `context-intelligence` — property graph over sessions/events/tool-calls/delegations. `thinking:*` captured. `LlmLifter` puts `model` + `provider` on every `llm:*` event. |
| Form signals | **Already a catalogue.** CI's `skills/workflow-pattern-analysis/signals-reference.md` — S1–S9, corpus-validated. Retry loops → S4c/S4d; re-reads → S7; non-convergence → S3; delegation → S9; context pressure → S1/P1a/P1b. Carries a retirement note: the naive "consecutive same tool" heuristic was killed at a 48% false-positive rate. |
| Off-hot-path capture | `context-intelligence-survey` — detached worker, numeric-only, consent gate, cohort tagging. Live-verified at v0.1.0. |
| Fade-check | `behavioral-plasticity` `falsification_harness` — `lift / retained / retention_ratio`, `Thresholds(proxy_ceiling, cognitive_floor, min_lift)`, `inconclusive` branch. Record schema **already carries `"ablation_mode": "memory"`** — the mechanism is already parameterized over what gets ablated. |
| Ledger | `memory` KG on amplifier-data; `hooks-behavioral-write` already does outcome→weight with reversible audited updates. |
| Cue injector | `hooks-memory-interject` — mid-session point-of-action injection with threshold, cooldown, max-chars, fail-open timeout. |
| Evidence-gated exit | `attractor` `PIPELINE_DESIGN_PRINCIPLES.md` §3: "The LLM is never the sole stop condition." §6 restates the evidence-links rule. |
| Boards / eval isolation | `amplifier-bundle-evaluation` DTU harness + `context-intelligence-eval-design` skill. Closes open question #4. |
| `preceptor-doctor` | `validate-bundle-repo` already enforces <500 / 500–1000 / >1000; `/audit-bundle` audits shape with file:line citations. **Delete it.** |
| Per-model resolution | `routing-matrix` — inverse axis (which model for the job vs. how much scaffold for the model), but proof that per-model resolution at session start is an accepted hook-shaped concern. |

**Gap that is genuinely new work:** no arbitration signal exists anywhere. P1b (thinking-block
share) is adjacent but measures volume, not conflict.

### The standalone decision

The author's constraint for the build is **core + foundation only**. That is a deliberate
trade, recorded here honestly:

- **Cost:** we reimplement the observer and the ablation arithmetic that
  `context-intelligence` and `falsification_harness` already provide, and we forgo a
  corpus-validated signal catalogue.
- **Benefit:** the bundle is installable by anyone with foundation, has no cross-repo
  release coupling, and can be adopted without buying into four sibling bundles.
- **Mitigation:** keep the on-disk formats flat and boring so migrating onto CI's graph or
  the falsification harness later is a reader change, not a rewrite.

Note: including foundation transitively pulls in recipes, skills, python-dev,
context-intelligence and more — foundation's own `includes:` list, which cannot be opted out
of. The constraint is satisfiable as: **preceptor's own `includes:` is foundation plus its
own behaviors, and every module `source:` is local.** A practical upside is that
`tool-recipes` arrives with foundation, so recipes are executable without declaring a
dependency.

---

## 4. Design defects — three critics converged on the same failure

### 4.1 The evidence is judgment wearing a counter's costume

`04-credential-schema.md:74` — *"Judgment proposes; evidence disposes."* The spec does not
earn it.

`opportunities` and `violations_recent` require a detector deciding "did the cue's trigger
arise" and "was it honored" from unstructured trajectories. That detector is never named,
never bounded, never given an error rate. It is a semantic LLM judgment rendered as an
integer.

A false `0 violations across 23 opportunities` is **indistinguishable in the ledger from a
genuinely solved problem**, and it directly licenses the `decay: 20` countdown. Violations
should be rare if a cue works, so this is a rare-event classifier — and rare-event
classifiers concentrate false negatives precisely where cost is highest.

> A counter nobody has calibrated against ground truth isn't evidence, it's an opinion with
> more decimal places.

**Fix:** before any autonomous action, hand-label a sample and publish the detector's
precision/recall. Absent that, counters may rank candidates but must not gate decisions.

### 4.2 The promote gate and the fade gate are the same test read in opposite directions

A live logical defect, at file:line:

- **Promote** (`04:66`): *"probes improve **or hold**."*
- **Fade** (`04:70`): *"A **flat** result moves the cue to faded."*

"Hold" and "flat" are the same measurement. A cue that changes behavior but not outcomes is
promoted on that evidence and later deleted on that same evidence. The only discriminator is
"observed behavior changed" — measured by the `[cue:id]` tag, which measures **compliance,
not benefit**.

Result: a stable churn population of cues that get promoted, doze, and get faded — motion
that reads as learning. `04:66` already states the intent (*"a cue that changes nothing gets
struck"*); the criterion contradicts it.

**Fix:** promotion requires a *strictly positive* delta at a pre-registered effect size.
"Hold" is not a promotion criterion. Express both predicates as code in one module with a
property test asserting no evidence tuple satisfies both.

### 4.3 The statistics do not exist, and survivorship bias eats the best cues

Every consequential decision rests on **one probe run per side**. No repetition count, no
variance model, no minimum detectable effect, no significance threshold in four documents.
At nonzero temperature, single-run A/B is indistinguishable from noise. "Flat licenses
deletion" is accepting the null from an underpowered test.

Worse: **any cue protecting against a rare-but-costly event is invisible to a fixed probe
suite and will be faded first.** That is the class of cue most worth having.

Two mechanical problems in the same family:

- **Observer effect.** A cue that *works* suppresses the trigger pattern the observer uses to
  count "opportunity." Opportunity count drops, the decay window closes faster, and working
  cues die *because* they work. Detect the trigger independently of whether the cue fired.
- **Interaction.** Cues are faded one at a time under an independence assumption never
  stated. Past small N, single-cue ablation is invalid and nothing flags the crossing.

### 4.4 The risk gradient is inverted

`03:58` already contains the right reasoning — cold start defaults to highest scaffold
because *"that is the safe direction to be wrong in"* — and never applies it to fading.

- **Adding a wrong cue** costs ~40 tokens and produces an observable behavior.
- **Deleting a right cue** costs a failure that reappears weeks later with **no attributable
  cause**. Reversible in principle, irreversible in practice, because absence is invisible.

The heavy evidentiary machinery sits on *entry*; removal is framed as a reward. **Flip it.**

**Shadow fade replaces hard fade:**

1. Cue reaches fade eligibility → `status: shadowed`
2. Stop dosing. **Keep counting** opportunities and violations against it.
3. Violations reappear in the window → auto-restore, auto-pin, notify.
4. Clean window → `status: faded`.
5. Track `false_fade_rate = restores / fade_attempts`.

`false_fade_rate` is the system's own trustworthiness metric and a shipping gate:
autonomous fading stays off until it is measured `< 0.10` over ≥40 attempts, and re-locks
automatically if it rises.

This one mechanism resolves the survivorship bias, the risk gradient, and the missing undo,
and produces the number that decides whether the thesis is true.

### 4.5 There is no human surface at all

`[cue:id]` is addressed to **the model**. Nothing is visible to the **human**. No receipt, no
digest, no diff, no `why`, no pin, no mute, no veto, no undo, no kill switch. Not thin —
absent.

Functionally that is a colleague editing your `AGENTS.md` nightly without telling you. The
behavior change is real and the cause is unattributable, which is the condition under which
people build *wrong* causal models — they blame the provider, a version bump, or their own
prompting, and act on those theories.

Minimum surface, three artifacts:

1. **Session receipt** — one line at session start when cues are active. Silent dosing
   prohibited.
2. **Immutable per-session dosing manifest** — content-hashed, so `why <session>` returns the
   *exact text dosed then*. Without it, "why did it do that last Tuesday?" is unanswerable,
   because the cue may since have faded and the reason been erased.
3. **Weekly digest, push not pull** — fades notified **before** dosing stops, with a
   one-command pin. A fade the user never saw is not a reversible decision.

Plus: the ledger is a git-tracked file, one commit per mutation, evidence ids in the message.
That satisfies "versioned and diffable" (`04:5`) literally rather than aspirationally.

**Security.** `dosed_at: tool-result:<tool>` blends instruction text into tool output. That
forges data provenance and is structurally identical to prompt injection — it makes the
ledger an injection vector into every session. Channel-separate it, and validate cue text on
write: length ceiling, no tool-invoking directives, no directives touching permissions or
approval behavior. **Ledger content is untrusted input.**

### 4.6 The metaphor: keep it in the thesis, get it out of the schema

**Accountability.** Hospital privileging's load-bearing part is not the record — it is a named
attending who signs, a committee, an appeals process, and liability attaching to a person.
The vocabulary is imported and all of that is dropped. "Privileges" carries institutional
accountability the system does not have, so the reader's prior about the word does work the
evidence has not earned. That is a confidence display exceeding evidence — the exact defect
the system exists to detect in models.

**The deeper break: the learner is frozen.** In medicine the resident improves, so decreasing
supervision over time is a justified prior — that is what licenses a decay schedule and a
one-directional step-down. Here the model does not learn. What changes is the scaffolding
and, critically, **the environment**: codebase, dependencies, task mix. The record is not
measuring competence acquisition. It is measuring **fit between a fixed model and a moving
target.**

Consequences:

- The monotone assumption is unjustified. No mechanism-level reason a cue's necessity
  declines with time.
- **Environment change should invalidate fades — not violations.** `04:72` lets a faded cue
  return when the codebase shifts *and violations reappear*, which means the system learns by
  letting the failure recur on the user. Instead: fingerprint the environment (dependency
  majors, domain file-pattern hash, model id); on fingerprint change, cues faded under the
  prior fingerprint return to shadow for revalidation.

**Practical version:** the ecosystem has no "credential," "boards," "chart review," or
"entrustment" concept, so every reader — human and model — maintains a translation table for
the life of the bundle. The clinical frame is excellent rhetoric in `01`. It is a
context-poisoning tax in the code. **Keep it in the thesis; drop it from the schema and CLI.**

### 4.7 `claude-opus-5` is not a stable identity

The record keys on a human-readable model string with no checkpoint fingerprint and no
re-assessment trigger on provider-side change. Providers swap weights behind stable
identifiers routinely. The record — including cues "proven" unnecessary — will keep governing
a model that no longer exists behind that string, silently.

---

## 5. Bundle conformance — four hard violations in `03-bundle-design.md`

1. **The "policy-behavior pattern" claim at `:40` is backwards.** Policy behaviors are
   app-composed, root-session-only, settings-gated. This is bundle-composed via `bundle.md`,
   always-on, and explicitly *not* root-only. That is `foundation:behaviors/logging.yaml`'s
   shape. The design choice is fine; the label misleads.
2. **`spawn.exclude_tools` does not do per-agent scoping** (`:72`). It is a blanket filter on
   whatever a session spawns. Differentiation comes entirely from per-agent `tools:` in agent
   frontmatter. Top-level `spawn:` is dead in practice — zero uses across every cached bundle.
3. **`preceptor-observe-only.yaml` has no entry point.** A behavior file is inert until
   included, and `bundle.md` includes only the full behavior. The adoption path does not
   exist as drawn. Needs `bundles/observe-only.yaml`.
4. **Direct contradiction:** `03:72` says write tools scope to "preceptor agents" (plural);
   `04:28` says "the credentialer agent is the only writer" (singular). Resolved by splitting
   the tool into a read surface (all agents) and a write surface (credentialer only).

**Also:** two independent full behavior YAMLs is the config-matrix anti-pattern.
`foundation:behaviors/redaction.yaml` proves a behavior's `includes:` can pull in another
behavior and layer on top. Compose, do not duplicate.

**And the irony that matters:** the design guards its static `context.include` against bloat
correctly, then puts **no token budget, no active-cue ceiling, and no truncation rule** on the
dynamic cues it injects into every session. The fade gate is deliberately slow (`decay: 20`);
promotion has no analogous ceiling. That is the accretion disease relocated from the bundle
into the record.

---

## 6. The design does not apply its own thesis to itself

Four places:

- `03:76` says *"watching before coaching applies to the bundle's own rollout"* — and Next
  Steps scaffolds all three modules and the full behavior at once, before either contract
  question was answered.
- It guards its own static context and leaves its dynamic payload unbounded.
- It argues context accretes because removal feels dangerous, then proposes a second parallel
  observation stack beside one that exists — the same failure mode at the repo layer.
- "Judgment proposes; evidence disposes," where the evidence is a judgment.

---

## 7. The strategic question the four documents never ask

Anthropic cut 80% **once, in one shot, by a human reading transcripts**, and lost nothing.

That is strong evidence that a **coarse, infrequent, whole-set, human-gated** intervention
works. It is not evidence that a **fine-grained, continuous, per-cue, autonomous** loop
works — and the fine-grained version is strictly harder to measure: smaller effects, more
noise, N-way interactions, and a semantic detector in the measurement path.

The thesis reads that result as "do this continuously and automatically." An equally faithful
read: *the coarse version already captures most of the value, and the only thing that failed
is that a human had to remember to do it.*

That points at a cheaper product — **automate the evidence assembly, not the decision.** A
scheduled run that observes continuously, assembles the case (here are the six cues with zero
violations across N opportunities, here is the whole-set ablation, here is the diff), and
hands a human a one-command approve. The trainer stays in the building; the trainer is still
a person. The entire thesis survives except autonomy — and autonomy carries all the risk, all
the statistical difficulty, and all the trust cost.

This is not asserted as correct. It is asserted as never argued against, and as the cheapest
version that survives every critique above.

**Corollary on measurement.** The best continuous outcome signal is probably not probes — it
is the **developer-correction turn**: how often the human says "no, do X instead." Free,
continuous, hard to game, needs no authored rubric per domain (which kills the combinatorial
probe-authoring cost nobody budgeted), and it is what the user actually feels. Probes for
gating; correction rate for the standing signal.

**Corollary on the unit of ablation.** Because cues interact, prefer ablating the **whole
active set** against the empty set periodically — which is exactly what Anthropic did and
exactly what `falsification_harness` already does for memory — and use per-cue counters only
as a *ranking heuristic for what to try removing first*, not as an evidentiary gate. One
large effect is measurable; N tiny ones are not.

---

## 8. Evaluation design

Two independent claims needing different experiments:

- **C1 (addition):** earned, per-model, per-domain cues improve work more than generic or
  mismatched cues.
- **C2 (deletion):** the fade gate can identify removable cues without losing value.

C2 is the load-bearing novelty (*"fading is what everyone skips"*) and the one nobody tests,
because a failed fade is invisible. **Test C2 first.**

### Experiment 1 — the sham-cue arm (tests C1)

Within-subject, blinded, N=12–16, 4 weeks, one domain, one model.

| Arm | Cues dosed |
|---|---|
| A | None |
| B | Earned cues from that developer's own record |
| C | **Sham:** earned cues from a *different* model and domain, matched on count and length |
| D | Generic best-practice cues, human-authored once, identical for all |
| E | **One-time human profile** — an engineer reads 50 sessions once, writes a profile, freezes it |

Arms C, D, E are the ones that matter. If **B ≈ C**, "earned" and "per-model" mean nothing
and this is an expensive generic prompt. If **B ≈ E**, the continuity claim is unsupported
and the correct product is a batch pass, not a runtime.

Primary outcome: **developer-correction turns per session**. Secondary: task success on
**held-out probes never used by the fade gate**, tokens-to-completion, wall-clock.

### Experiment 2 — randomized shadow fade (tests C2; ship this as instrumentation, not a study)

Every cue reaching fade eligibility is randomized: 50% removed from dosing, 50% retained.
Both arms keep being counted. Primary outcome: `false_fade_rate`, ceiling `< 0.10`.

Cheap, runs in production, needs no separate cohort, and produces the single number that
determines whether the system's central claim is true.

### Non-negotiables

- **Gate probes and eval probes must be provably disjoint.** A system that grades itself on
  its own gate is unfalsifiable.
- Blinded efficacy runs only in an explicitly consented cohort who know they are in a study.
  Do not ship blind to non-consenting users and call it a rollout.
- Track **observed-session share** — a falling share is the signature of chilling effects and
  is a defect, not low engagement.

---

## 9. Recommended build order

```
v0  INSTRUMENT, NOT FEATURE — no injection at all.
    - Observer writes RAW structural records. No semantic taxonomy.
    - Consent gate, default off. Session receipt. Schema-constrained records.
    - Dump observed payload shapes; treat that as the real event schema.
    - Calibrate the opportunity/violation detector against hand-labeled truth.
      Publish precision/recall. This is the gate for v1.

v1  ONE CUE, END TO END, HUMAN-APPROVED.
    - Injector on provider:request, priority 20, channel-separated.
    - Whole-set ablation before per-cue ablation.
    - Shadow fade, never hard fade. false_fade_rate instrumented from day one.
    - Every promote and every fade is a human approve.
    - Prove ONE real cue fades on evidence.

v2  AUTONOMY, EARNED — and only by the system's own rules.
    - Autonomous fade unlocks at false_fade_rate < 0.10 over >= 40 attempts.
    - Re-locks automatically if it rises.
```

Both `core-expert` and `crusty-old-engineer` independently arrived at the same warning:

> Don't build the write surface yet. There are no observations to propose from, so the cue
> taxonomy and the write API would be authored from priors against zero evidence — which is
> precisely the failure mode this bundle exists to prevent. Don't have the preceptor commit
> the sin it was built to catch.

---

## 10. Doc-level fixes to make before further design work

| Location | Fix |
|---|---|
| `04:66` vs `04:70` | Promote/fade predicate collision — promotion requires strictly positive delta |
| `03:72` vs `04:28` | Plural/singular writer contradiction — split read and write surfaces |
| `03:40` | Remove the "policy-behavior pattern" label |
| `03:72` | Remove the `spawn.exclude_tools` claim |
| `03:38` | Remove "never adds latency" — buffer and flush instead |
| `03:40` | Strike the log-tailing fallback |
| `03:54`, `03:80-81`, `03:88` | Strike both core questions and the escalation step — answered |
| `03:68` | Delete `preceptor-doctor` — `validate-bundle-repo` covers it |
| `03:83` | Open question #4 (eval isolation) — answered by the DTU harness |
| `01:32` | Economics claim is asserted with no numbers; fade-check is 2x a probe suite per cue per credential per provider×model×domain |
| Throughout `03`/`04` | Drop `privileges` / `boards` / `chart review` / `entrustment` from schema and CLI; keep in `01` |

---

## 11. What survives, plainly

The asymmetry is real and well-evidenced. The removal mechanism is genuinely missing from
every context system, including this one. `[cue:id]` as a correlation key is a real
invention. Per-model scaffolding is a real requirement for a multi-provider runtime.

What needs to change is not the thesis. It is the confidence: the measurement has to be
calibrated before it can gate anything, the risk gradient has to be flipped so that removal —
not addition — carries the burden of proof, and a human has to be able to see and undo what
the system did.

Described plainly, this is **regression-tested prompt scaffolding with an ablation-based
reachability test** — a garbage collector for instructions. Less evocative, much easier to
trust, and that is the right trade for a system that edits people's sessions.
