# What counts as evidence

The whole system rests on one sentence: *judgment proposes, evidence disposes.* That is only
true if the evidence is not itself a judgment. Most of the ways this fails are listed below.

## The counter problem

`opportunities` and `violations_recent` require deciding two things from an unstructured
trajectory: did the cue's trigger condition arise, and was the cue honored. Both are semantic
judgments. Writing them as integers does not make them measurements.

A false `0 violations across 23 opportunities` is **indistinguishable in the ledger from a
genuinely solved problem** — and it is what starts the retirement clock. Violations are rare
when a cue works, so this is a rare-event classifier, and rare-event classifiers concentrate
their false negatives exactly where the cost is highest.

**Therefore:** the detector must be scored against hand-labeled ground truth, and its
precision and recall must be written into `state.json`, before any counter is allowed to gate
anything. Until then counters may *rank* candidates. They may not *decide*.

## The power problem

A single probe run per side cannot distinguish a real effect from sampling noise at nonzero
temperature. "Flat licenses deletion" is accepting the null hypothesis from a test that was
never shown able to detect the effect.

Minimum bar for any comparison used as a gate:

| Requirement | Why |
|---|---|
| n ≥ 5 runs per arm | One run per side measures noise |
| Report variance, not just the mean | A mean without a spread is not a result |
| Pre-register the minimum detectable effect | Otherwise "flat" is unfalsifiable |
| Distinguish "confident no-effect" from "underpowered" | These license different actions |

An underpowered comparison yields `inconclusive`, and `inconclusive` **keeps the cue**. Only
a confident no-effect retires one.

## The economics, honestly

The claim that observation "amortizes offline, in batch, on cheap models" is currently
asserted with no numbers behind it. Meanwhile an ablation is 2× a probe suite, per cue, per
provider × model × domain — and per-triple granularity is the design's own selling point, so
it multiplies on exactly the axis that costs the most.

Model this before scaling the loop. Whole-set ablation (see `cue-lifecycle.md`) is cheaper by
roughly the cue count and is statistically stronger. Prefer it.

A cheaper standing signal exists and should be preferred to probes for continuous
measurement: **the developer-correction turn** — how often the human says "no, do X instead."
It is free, continuous, hard to game, requires no authored rubric per domain, and it is the
thing the user actually feels. Probes for gating; correction rate for the standing signal.

## Evidence references

Every ledger mutation carries a reference and the tool refuses without one.

| Field | Must reference | Refused when |
|---|---|---|
| `origin` | Observation ids that exist on disk | Empty, or ids not found |
| `entry_evidence` | An assessment run showing a strictly positive delta | Missing, or delta ≤ 0 |
| `exit_evidence` | An assessment run with a confident no-effect | Missing, or `inconclusive` |

An id that does not resolve is a hard failure, not a warning. An unresolvable evidence
reference is worse than no reference, because it looks like a gate passed.

## Cue text is untrusted input

The ledger is read by the injector and its contents are placed into a live session. Treat it
as an injection vector, because that is what it is. `credentialer` validates on write:

- Length ceiling (`max_cue_chars`, default 200).
- No directive that invokes a tool.
- No directive touching permissions, approvals, or gating behavior.
- No attempt to redefine the cue protocol itself.

Cue text is delivered in a labelled block of its own. It is **never** blended into a tool
result: doing so forges data provenance and is structurally identical to prompt injection.

## Routing a learning to the right place

Not every learning is a cue, and the cheapest way to keep the ledger honest is to keep things
out of it that do not belong.

| Learning | Home | Why |
|---|---|---|
| This model needs a nudge here | Cue in the ledger | Model-specific; should fade |
| This codebase has a gotcha | Project context file | Holds for any model; should not fade |
| A repeatable procedure | A skill | Loaded on demand, not dosed |
| A user preference | Memory | Belongs to the user, not the model |

A model-independent fact in a per-model ledger will never fade correctly, because its
necessity has nothing to do with the model.
