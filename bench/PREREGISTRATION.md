# Pre-registration — instruction-set calibration

*Written before any calibration run. Hash is recorded in every run report; if it
changes mid-run, the run is void.*

```
sha256  164abb3cb4c27aee8e2c54f1deddd5abf39687fe4057ece7cd98acf122d86dc7
```

The point of pre-registering is that thresholds chosen after seeing results are not
thresholds, they are rationalizations. Everything below is fixed in advance.

---

## 1. Hypotheses

**H1 (addition).** Cues earned from observed failures reduce developer-correction
turns relative to no cues.

**H2 (removal).** Some instructions in a mature set are inert, and removing them
costs nothing measurable.

**H0 for both.** No effect. **A null result is a publishable outcome**, not a failed
run. The only peer-reviewed instruction-ablation study in the literature
(arXiv:2601.20404, 10 repos / 124 PRs) found that *adding* an `AGENTS.md` cut median
runtime 28.64% and output tokens 16.58% — i.e. it favors addition. If this
calibration reproduces that direction, that is the finding, and it gets reported.

---

## 2. Metrics

| Role | Metric | Direction | Source |
|---|---|---|---|
| **Objective** | developer-correction turns per task | lower better | `correction_turns.py` |
| **Constraint** | task success rate | higher better | executable rubric exit code |
| Secondary | redirect-class corrections | lower better | `correction_turns.py` |
| Secondary | root-context tokens | lower better | `events.jsonl` |
| Secondary | wall clock | lower better | trial `state.json` |

No LLM judge appears anywhere in the measurement path. arXiv:2608.22960 showed
full-trace judges exhibit systematic collider bias — they score semantic relevance
rather than causal contribution, which means a judge-based trajectory metric is
measuring the wrong quantity from the first run.

---

## 3. Thresholds — fixed before the first trial

```
alpha                 0.05     one-sided
power                 0.80
min_n_per_arm         5        hard floor; verdict.py refuses below this
effect_size_floor     0.50     |Cohen's d|; below this is not distinguishable

ni_margin             0.02     per-move tolerable loss in task success rate
total_loss_budget     0.05     FIXED total across the whole run
max_accepts           10       so ni_margin <= total_loss_budget / max_accepts... (*)

plateau_patience      2        consecutive iterations with no accept
anchor_every          3        accepts between anchor re-checks
max_iterations        8
```

(*) `0.05 / 10 = 0.005`, which is stricter than the `0.02` chosen. The relaxation is
deliberate and is what the anchor exists to cover: rather than demand ~37,000 paired
evaluations per removal (see §5), each move gets a workable margin and the
**anchor** enforces the real constraint against the original baseline. If the anchor
breaches, the run stops and the champion is rolled back. The per-move margin is a
filter; the anchor is the gate.

---

## 4. Accept rules — asymmetric, and that is the whole design

### Addition — superiority

```
ACCEPT iff   verdict(corrections) == "positive"  AND  delta < 0
             AND non-inferiority holds on task success
```

An addition must **earn** its place. `no-effect` and `inconclusive` both reject.

### Removal — non-inferiority, batched

```
ACCEPT iff   upper_bound_95(loss in success) < ni_margin
             AND corrections did not significantly worsen
```

Three things are deliberate here:

1. **Not "the drop wasn't significant."** That is failure-to-reject, and an
   underpowered test manufactures it for free. The non-inferiority bound gets
   *wider* with less data, so a small sample **fails** rather than passing by
   default.
2. **Removals are batched.** With `total_loss_budget / m` margins and required n
   scaling as `1/δ²`, ten single removals at δ=0.5pp would need ~37,000 paired
   evaluations *each*. One batch of ten at δ=5pp needs ~100× fewer.
3. **No improvement is required.** The point of a removal is that the instruction
   was inert; demanding an improvement would reject exactly the removals worth
   making.

### Multiple comparisons — deliberately NOT corrected on removals

Bonferroni/FDR is correct for additions (Type I error on a superiority test) and
**actively harmful** for removals: shrinking α makes harm *harder* to detect, so
more removals sail through. The compounding risk is handled by the anchor instead.

---

## 5. Overfitting controls

**Three-way split, code-enforced** (`splits.py`). `confirm` raises
`SealedSplitError` on any read until `unseal_for_gate()` is called explicitly, and
every unseal is logged so a report can show whether the run peeked.

| Split | Used for | Default |
|---|---|---|
| `harvest` | proposing cues from observations | 40% |
| `climb` | evaluating candidates (burned) | 30% |
| `confirm` | **sealed**; read once, at the end | 30% |

Justification, from RSEA (arXiv:2606.28374) ablating exactly this gate:

| Variant | in-sample | test |
|---|---|---|
| baseline, no evolution | — | 63.6 |
| **no held-out gate** | **100.0** | **66.7** |
| strict held-out gate | — | 67.3 |

Selecting on the evolution set drives in-sample to a perfect 100% and leaves a
33-point train/test gap.

**Admissibility gate** (`climb.admissible`) rejects task-specific edits *before* any
rollout. HarnessCompass (arXiv:2608.01918) reports this alone bought +6.8pp held-out
in 2 turns for zero extra evaluations, by shrinking the space so the search cannot
express the overfit.

**Monotone-safe.** Following RSEA: lateral (≥) acceptance on the working state to
cross plateaus, strict (>) update on the frozen champion. If nothing strictly
improves, the baseline is returned.

**Anchor re-check** against the ORIGINAL baseline every 3 accepts. This is the only
defense against the failure ACE (arXiv:2510.04618) measured directly: context
collapsed from 18,282 tokens @ 66.7 accuracy to 122 tokens @ 57.1 — *below* the 63.7
no-adaptation baseline. A remove-capable climber is a ratchet pointed at the empty
prompt unless something compares against where it started.

---

## 6. Validity gates — the run is void if these fail

1. **Negative control.** The `bloat` arm is a known-bad instruction set. If the
   accept rule does not reject it, the harness cannot detect a planted regression
   and nothing it reports means anything. Reported at the top of the run report, not
   in a footnote.
2. **Split disjointness.** Asserted by test; empty intersection required.
3. **Confirm access count.** Must be exactly 1 at report time.
4. **Pre-registration hash.** Must match the hash recorded at run start.
5. **Prediction is never a gate.** Each mutation may carry a `predicted_effect` as a
   falsifiable contract, logged and scored afterwards. It has no influence on
   acceptance. AHE (arXiv:2604.25850) measured an evolver predicting its own
   regressions at 11.8% precision / 11.1% recall — roughly 2× chance. Predicted-no-harm
   is not evidence of no harm.

---

## 7. Stopping

The climb halts on the first of:

- `max_iterations` (8)
- plateau: `plateau_patience` (2) consecutive iterations with no accepted move
- proposer returns no admissible moves
- **anchor breach** — cumulative loss vs. the original baseline exceeds
  `total_loss_budget`

Anchor breach is a **failure stop**: the champion is rolled back to the last
anchor-clean state and the run is reported as breached.

---

## 8. What gets reported regardless of outcome

- Every accepted **and** rejected mutation, with its reason. A rejection without a
  cause is refused at write time.
- The negative-control result, first.
- Confirm-split numbers, computed once.
- Power actually achieved (`verdict.required_n`) versus what was needed.
- If the result is null: **said plainly, in the README, without hedging.**

The project's value is not in removal turning out to help. It is in being the
apparatus that can tell you, and being willing to publish the answer when it comes
back negative.
