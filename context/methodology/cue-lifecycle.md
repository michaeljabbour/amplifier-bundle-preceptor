# Cue lifecycle

```
                  ┌──────────────────────────────────────────┐
                  │                                          │
   observations ──▶ proposed ──▶ active ──▶ shadowed ──▶ faded
                       │           ▲          │  │            │
                    struck         └──restore─┘  └────────────┘
                                    (auto-pin)   environment change
```

Four states. Two irreversible-looking transitions that are, deliberately, reversible.

## proposed

`form-analyst` surfaces a candidate from observation records. `skeptic` attacks it: the cue
must be traceable to a mistake **that actually occurred**, with observation ids. A candidate
written from priors, from a general best practice, or from fear of what the model *might* do
is struck here.

Survivors enter `proposed` and are dosed live so their effect can be measured.

## proposed → active

**Requires a strictly positive delta at a pre-registered effect size.**

This is a correction to the original design, which admitted a cue when probes *"improve or
hold"* and removed one when probes were *"flat"* — the same measurement in both directions.
Under that rule a cue with no effect is admitted on the same evidence that later deletes it,
producing a churn population that reads as learning and is not.

`credentialer` MUST enforce that no evidence tuple satisfies both `promote()` and `retire()`.
There is a property test for exactly this.

Behavior change alone is **not** promotion evidence. The `[cue:id]` correlation measures
compliance, not benefit.

## active → shadowed

Eligibility is a *ranking heuristic*, not a verdict: violations at zero across the cue's
window suggests trying removal first, nothing more.

**Shadowed means dosing stops and counting continues.** The window is
`shadow_window_days` OR `shadow_window_opportunities`, whichever is longer.

- Violations reappear → **auto-restore, auto-pin, notify immediately.** Increment
  `shadow_restores`.
- Window closes clean → `faded`, with `exit_evidence` recorded.

Every shadow transition emits a notification **before** dosing stops, naming the cue text
verbatim and giving a one-command pin. A retirement the user never saw is not a reversible
decision, whatever the state machine says.

## faded

Removed from dosing, retained in the document with its evidence. Returns to `shadowed`
automatically when `model_fingerprint` or `environment_fingerprint` changes.

## The gates

### Removal carries the burden of proof

Adding a wrong cue costs a few tokens and produces a visible behavior. Removing a right one
costs a failure that reappears weeks later, which the user experiences as "the model got
worse" rather than "something was removed." The design's own cold-start rule already says
the high-scaffold direction is *"the safe direction to be wrong in."* This applies it
consistently.

### Autonomy is earned

`autonomous: false` is the default and it is not ceremony. Promotion and retirement require
human approval until **both**:

- `detector_calibrated` is true — the opportunity/violation detector has been scored against
  hand-labeled ground truth and its precision/recall are published, **and**
- `false_fade_rate < false_fade_ceiling` over at least `min_fade_attempts`.

The lock re-engages automatically if the rate rises. An uncalibrated counter is not
evidence; it is an opinion with more decimal places, and gating on it would make the system
commit the failure it exists to catch.

### Ablate the set before the cue

Cues interact. One-at-a-time ablation assumes independence that nothing here establishes,
and it degrades silently as cue count grows.

So: **ablate the whole active set against the empty set first.** One large effect is
measurable; N small ones drown in sampling noise. That whole-set comparison is also the only
version of this experiment anyone has actually run in the wild, and it worked. Per-cue
counters rank what to try removing first; they do not settle it.

### The probes that gate are not the probes that grade

Gate probes and evaluation probes must be provably disjoint. A system that grades itself on
its own gate is unfalsifiable. There is a test asserting the intersection is empty.

## Survivorship bias — the failure to watch for

A cue that protects against a **rare but costly** event is nearly invisible to a fixed probe
suite. Under a naive fade policy it is the *first* thing retired — which means the policy
preferentially deletes the highest-value entries.

Two defenses: the shadow window (a rare event still has time to reappear), and
`origin_class: human` cues, which are never auto-retired at all.

## Observer effect — the counter that lies

A cue that *works* suppresses the very trigger pattern used to detect an "opportunity." The
opportunity count falls, the window closes sooner, and working cues are retired **because**
they work.

Detect the trigger condition independently of whether the cue fired. If that is not possible
for a given cue, it is not eligible for autonomous retirement — say so on the cue rather
than letting the counter quietly decide.
