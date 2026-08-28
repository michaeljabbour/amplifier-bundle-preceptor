# Probes

A probe is a canary task plus a **rubric that executes**. Prose descriptions of quality are
not rubrics — they relocate the judgment into a grader and hide it there.

```
probes/<domain>/<probe-name>/
├── probe.yaml       # task, arms, minimum detectable effect
├── rubric.sh        # exits 0 on pass, non-zero on fail. THIS is the grade.
└── fixture/         # whatever the task operates on
```

## Two pools, provably disjoint

| Pool | Used for | Rule |
|---|---|---|
| `gate` | Deciding whether a cue enters, stays, or retires | Never used to evaluate the system |
| `grade` | Evaluating whether the system helps a real developer | Never used to gate a mutation |

A system that grades itself on its own gate cannot be falsified. `pool:` in `probe.yaml` is
required and a test asserts the intersection is empty.

## The statistical bar

`preceptor:assessor` refuses a comparison that does not meet it:

- `n >= 5` runs per arm — one run per side measures sampling noise, not effect
- report mean **and** variance
- pre-register `min_detectable_effect` **before** running
- emit `positive` / `no-effect` / `inconclusive`, never a bare pass/fail

`inconclusive` keeps the cue. Only a confident no-effect retires one.

## Ablation order

Ablate the **whole active cue set** against empty before ablating any single cue. One large
effect is measurable; N small ones drown. Per-cue counters rank what to try removing first;
they do not settle it, because cues interact and single-cue ablation assumes an independence
nothing here establishes.

## Cost

An ablation is 2x a probe suite, per cue, per provider x model x domain. Keep probes cheap and
few. The claim that this "amortizes on cheap models" has no numbers behind it yet — record the
real cost of every run so it eventually does.
