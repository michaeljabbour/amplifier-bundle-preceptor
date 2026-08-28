# Preceptor

**Watch the natural behavior. Correct against what you observed. Keep only the corrections that prove their impact.**

An Amplifier bundle that runs the clinical precepting loop on AI agents: observation before instruction, evidence before correction, impact before tenure.

Working notes, August 28, 2026.

## The theory

Three commitments, in order, none skippable.

**1. Observation comes first.** You cannot correct behavior you have not watched. Preceptor reads the agent's natural form in real work: how it reasons and reflects, how it chooses and sequences tools, how it recovers from errors, where it hesitates or re-reads, and where it arbitrates between instructions that disagree. No instruction changes until natural behavior is on record, the way a clinical preceptor watches a resident work a live case before saying a word. Benchmarks score the outcome; form shows up only in the trajectory, and form is where you learn why something works or fails.

**2. Corrections target observed behavior.** A correction, a cue, enters only from evidence: a specific failure that occurred, linked to the sessions where it happened. It is the smallest intervention that changes the behavior, delivered at the moment of the relevant action rather than piled at the top of a prompt. Nobody writes a cue from priors or from fear of what the model might do.

**3. Corrections must prove their impact, twice.** A new cue is a hypothesis. It earns tenure only when the observed behavior changes and the result improves. Tenure then has to keep being earned: when the behavior holds without the cue and results stay flat on a controlled removal, the cue fades, with the evidence recorded. Entry gated by impact, retention gated by continued need, removal gated by proof. Medical education calls this the entrustment scale: supervision steps down as competence is demonstrated, and each step down is a documented decision.

What accumulates is a credential, or in hospital vocabulary, privileges: a per-model, per-domain record of demonstrated competence, every entry linked to the observations and eval runs behind it. The system earns it from evidence rather than authoring it from priors.

## Why this matters now

Anthropic removed over 80% of Claude Code's system prompt for Claude 5 generation models and measured no eval loss, which proves that static instruction decays into overconstraint as models improve. Read closely, though, their correction cycle was human: engineers watching transcripts, deleting, gating on evals, once per model generation. Preceptor makes that cycle a standing runtime function, and makes it per model, so a runtime fronting several model families keeps a separate, current privileges record for each instead of one instruction sheet aging in place.

## Vocabulary

| Term | Meaning |
|------|---------|
| **Form** | The trajectory: reasoning, reflection, tool use, recovery, arbitration |
| **Cue** | The smallest evidence-backed correction, dosed at the point of action |
| **Privileges** | The earned per-model, per-domain credential, with evidence links |
| **Boards** | Baseline probes with executable rubrics for a new model or domain |
| **Chart review** | The offline batch pass that proposes cues and candidate fades |
| **Entrustment** | The fading discipline: supervision steps down as evidence allows |

## Files

| File | Contents |
|------|----------|
| `01-preceptor-thesis.md` | The framework: form versus outcome, the four primitives, why fading is the skipped step, and why per-model privileges belong in the platform layer |
| `02-research-notes.md` | Source material read through the frame: Anthropic's six context shifts, the dynamic workflows machinery, the Amplifier bundle system inventory |
| `03-bundle-design.md` | Full design for `amplifier-bundle-preceptor` in native constructs, with open core-contract questions |
| `04-credential-schema.md` | The privileges ledger: observation records, cue lifecycle, entrustment, portability over the Open Session Protocol |

## Status

Design stage. Next step is scaffolding the repo: `bundle.md`, `behaviors/preceptor.yaml`, hook module stubs against the `mount()` contract, and the boards probe structure. Two questions for `amplifier-core` gate the injector design and are flagged in `03-bundle-design.md`.
