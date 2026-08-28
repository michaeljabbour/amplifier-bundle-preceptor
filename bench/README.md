# Does Preceptor help or hurt?

```bash
python3 bench/run.py              # 3 arms x 3 tasks x 5 trials = 45 runs, ~6 min
python3 bench/run.py --trials 3   # faster, and it will tell you it is underpowered
```

## Three arms

| Arm | Bundle | Isolates |
|---|---|---|
| `control` | none | Baseline — Amplifier as you already run it |
| `observe-off` | `bundles/observe-only.yaml` | Cost of **loading** the bundle with recording off |
| `observe-on` | `bundles/observe-on.yaml` | Cost of **actually recording** |

Splitting off from on matters: they answer different questions. If `observe-off` is
free but `observe-on` is not, the cost is in the capture path. If both cost the same,
the cost is in bundle resolution and has nothing to do with the observer.

Each trial runs in a throwaway `AMPLIFIER_HOME`, so trial N cannot inherit state
from trial N-1.

## What it measures

- **Overhead** — wall-clock per run, mean ± stdev, versus control.
- **Harm** — did every session exit 0, return the right answer, and stay quiet on
  stderr? Tasks are deterministic and regex-checked, so no grader model is in the
  loop to launder a judgment as a measurement.

## What it deliberately does not measure

**Benefit.** No cues have been earned yet, so there is nothing to dose. A benefit
number produced here would be authored from priors — which is the precise failure
this bundle exists to catch. Refusing to print one is the bundle passing its own
test.

The experiment that would settle it is designed and written down in
[`docs/theory/05-expert-review.md`](../docs/theory/05-expert-review.md) §8: a
within-subject study whose decisive arms are a **sham** (cues earned on a
*different* model and domain, matched on count and length) and a **frozen one-time
human profile**. If earned cues do not beat the sham, "earned" and "per-model" mean
nothing and this is an expensive generic prompt. If they do not beat the frozen
profile, the continuous loop is unjustified and the right product is a batch pass.
Both are live possibilities. Neither is answerable until real cues exist.

## Verdicts, not pass/fail

Same bar the bundle applies to itself
([`evidence-standards.md`](../context/methodology/evidence-standards.md)):

| Verdict | Means |
|---|---|
| `positive` | Effect detected, n ≥ 5 per arm, \|Cohen's d\| ≥ 0.5 |
| `no-effect` | Adequately powered **and** the effect is below detectable |
| `inconclusive` | Underpowered — the test could not have found the effect |

`inconclusive` is a real answer. Reporting `no-effect` from an underpowered
comparison is accepting the null from a test that could never have rejected it,
and it is the most common way a benchmark like this lies.

For Preceptor, `no-effect` on overhead is the **desired** result: the observer
claims to sit off the model's path, and this is the check on that claim.

Results land in `bench-results/latest.json` (gitignored — they are machine-specific).
