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

## Final run, 2026-08-30 — DTU, n=30, working observer, all arms warmed

The first run that measures what it claims to. The observer records (662 records),
every arm gets an identical warm-up, and the numbers are adequately powered.

| Arm | run time | provision | correct | records |
|---|---|---|---|---|
| baseline | **5.01s ± 1.12** | 91.0s | 30/30 | 0 |
| observe-off | **11.95s ± 1.10** | 91.4s | 30/30 | 0 |
| observe-on | **11.59s ± 1.01** | 89.5s | 30/30 | **662** |

```
OVERHEAD vs baseline
  observe-off   positive   delta=+6.940 (+138.5%)  d=+6.26  t=24.25 df=58.0
  observe-on    positive   delta=+6.579 (+131.3%)  d=+6.17  t=23.90 df=57.4

HARM    none — 90/90 correct
POWER   n=30. Need ~25 for d=0.8. Bar met.
```

### The finding, stated plainly

**Composing Preceptor costs ~6.9s of session startup — a 138% increase on a
trivial task.** That is not a rounding error and it is not noise: d=6.26, t=24.
It is the single largest effect measured in this project, and it is a cost, not
a benefit.

**Recording is free.** `observe-on − observe-off = −0.36s`, i.e. within noise and
nominally negative. The entire cost is in *loading* the bundle — three modules,
four agents, and context files — not in the observer doing its job.

That split matters for what to do about it. The observer's design goal was to
sit off the model's hot path, and it does. The bundle's *composition* is what
is expensive, which is a packaging problem with obvious levers (lazy module
activation, thinner default composition, agents loaded on demand) rather than a
fundamental one.

### Why the earlier "no-effect" was wrong

The 2026-08-29 run below reported `no-effect` at the same n=30. It was measuring
an inert bundle: the observer never mounted, so `observe-on` and `observe-off`
were the same arm, and both were composed by a path (`bundle add --app`) that did
not load the hook at all. Three defects had to be fixed before this number could
exist — see `docs/theory/06-empirical-program.md` §11.

### Two artifacts caught and killed on the way here

Both would have produced confident, publishable, wrong numbers.

1. **Cold resolution counted as bundle cost.** Passing `--bundle <git-url>` per
   trial re-resolves from git on every run: +28.1s on `observe-off`, +28.6s on
   `observe-on`, +0s on baseline. Both bundle arms, neither baseline — that is
   resolution, not bundle overhead. Reported as-is: a fabricated **+74%
   regression**, with d=7.37 and t=28.5 behind it.

2. **Warming only the treatment arms.** The fix for (1) warmed the cache during
   provisioning for bundle arms only, which made them look **3.5× faster** than
   baseline (10.5s vs 38.0s). Mirror image of the same error.

The tell in both cases was the same and it is worth keeping: **an effect that
appears in every treatment arm but not the control is usually a property of how
the arms were built, not of what they contain.**

---

## Second run, 2026-08-29 — DTU, n=30 per arm (POWERED)

90 isolated containers, one per trial, destroyed after. 12.9 min wall at 8-way
concurrency on the resized VM.

| Arm | run time | launched | exit ok | correct |
|---|---|---|---|---|
| baseline | **37.95s ± 1.86** | 30/30 | 30/30 | 30/30 |
| observe-off | **37.65s ± 2.03** | 30/30 | 30/30 | 30/30 |
| observe-on | **37.83s ± 2.32** | 30/30 | 30/30 | 30/30 |

```
OVERHEAD vs baseline
  observe-off   no-effect   delta=-0.300 (-0.8%)  d=-0.15  t=-0.60 df=57.6
  observe-on    no-effect   delta=-0.125 (-0.3%)  d=-0.06  t=-0.23 df=55.4

HARM      none — 90/90 trials completed with the correct answer
POWER     n=30 usable. Need ~25 for d=0.8. Bar met.
```

**This supersedes the n=5 run below.** That one could only say `inconclusive`.
This one is adequately powered for a large effect and returns a real
`no-effect`: composing the Preceptor bundle costs nothing measurable, and both
deltas are *negative* (nominally faster), which is what noise looks like.

**What this does NOT measure — and the reason is a bug.** `observe-on` wrote
**0 observation records**. The observer's `config:` block is not reaching its
`mount()` through bundle YAML, so the consent gate reads `enabled=False` and it
registers no handlers. `observe-on` and `observe-off` are therefore *the same
arm*, and the cost of actually **recording** is unmeasured. See
[`docs/theory/06-empirical-program.md`](../docs/theory/06-empirical-program.md)
§11.2 for the isolation:

```
mount(config={"enabled": True, ...})  -> 13 handlers, file written   module OK
mount(config={})                      ->  0 handlers, nothing        what it gets
```

The gate fails **closed**, which is the right direction — nobody has been
recorded who didn't ask to be.

---

## First run, 2026-08-28 (macOS arm64, claude-opus-5, n=5 per arm)

| Arm | wall-clock | sessions ok | answers ok |
|---|---|---|---|
| control (no preceptor) | **30.68s ± 0.54** | 5/5 | 5/5 |
| observe-on (recording) | **31.21s ± 0.36** | 5/5 | 5/5 |

```
delta   +0.53s (+1.7%)   d = +1.16   Welch t = 1.84, df = 6.9
VERDICT inconclusive — d is large but n is too small to confirm
HARM    none — every session completed, every answer correct, stderr identical
```

**Read that verdict carefully, because the first version of this harness got it
wrong.** It gated on Cohen's d alone, saw d = 1.16, and printed `positive`. But
Welch's t on the same data is 1.84 at df ≈ 6.9 — roughly p ≈ 0.11, nowhere near
significant. Five samples cannot establish a 1.7% effect.

The benchmark committed the exact error the bundle it measures exists to catch:
a confident verdict from a test that could not support it. `verdict()` now
requires both a meaningful effect size *and* significance, and returns
`inconclusive` when d is large but n is not.

`inconclusive` means **keep looking**, not "no effect." The honest summary is:
observing costs somewhere between nothing and about half a second per session,
and it demonstrably breaks nothing. Establishing which end of that range needs
n ≈ 30 per arm.

**Function check** (separate from timing): the treatment arm wrote 37 observation
records across the run, and every record carried only the 14 structural fields —
no message text, no file contents, no paths. The observer is doing real work,
not merely loading.

---

## The ablation harness (DTU-based)

`bench/run.py` measures overhead locally. The real experiment runs in DTUs via
`amplifier-bundle-evaluation`, whose A/B lever is `agents/<id>/install.yaml` — two
agent dirs differing only in their `bundle add` line.

| File | Does |
|---|---|
| `arms/` | Six agent definitions. See `arms/README.md` for why each exists. |
| `correction_turns.py` | **The novel metric.** Counts developer-correction turns from a transcript. Judge-free. |
| `aggregate.py` | Trial results → per-arm statistics → verdicts vs. control. |
| `verdict.py` | The one implementation of the statistics. Imported, never copied. |

```bash
amplifier-evaluation run --agents-dir bench/arms --tasks-dir <tasks> \
  --agent baseline --agent preceptor-on --agent sham \
  --trials-per-pair 25 --max-parallel 2 \
  --output-dir bench-results --run-id ablation-001

python3 bench/aggregate.py bench-results/ablation-001 --control baseline --json
```

### Correction turns — why this metric

`amplifier-bundle-evaluation` drives trials with an **AI User** whose system prompt tells
it, verbatim (`ai_user.py:122-129`), to send a follow-up whenever the agent stops early:
*"go ahead", "yes", "proceed", or a brief direct answer*.

That is a scripted developer issuing corrections, and **nothing counts them.** A search
across the evaluation, ergonomics, feedback, behavioral-plasticity, context-intelligence
and survey bundles found zero implementations. The closest named artifact,
`context-intelligence/modules/tool-user-repetition/`, contains only a stale `__pycache__`.

The metric is cheap precisely because the nudge policy is already written down as an
instruction — a rule the agent is *told* to follow is a rule you can count against. That
system prompt is simultaneously the behavior spec and the labeling function.

```bash
python3 bench/correction_turns.py --detail path/to/transcript.jsonl
```

Four classes, cheapest to most expensive: `nudge` ("go ahead") → `clarification`
("use the second one") → `substantive` (new requirement) → `redirect` ("no, use pytest
instead" — work was done wrong and must be undone).

**It found its own bug on first contact with real data.** Pointed at 12 real transcripts,
it scored one session at 6 corrections when the truth was 3: `<system-reminder>` and
`<turn_aborted>` blocks arrive with `role=user` and were being classified as `redirect`.
That inflates every arm by an amount that varies with how much platform machinery fired —
it would have looked like a real effect. `test_platform_machinery_is_not_a_correction`
locks the fix.

### Deliberately no LLM judge, anywhere

arXiv:2608.22960 (Aug 2026) shows full-trace LLM judges exhibit **systematic collider
bias**: shown a whole trajectory they score *semantic relevance*, not *causal
contribution* — picking the step that looks decisive in hindsight rather than the one that
changed the outcome. The obvious way to score trajectory quality measures the wrong thing
from day one. Every metric here is deterministic.

### Power, stated up front

`verdict.required_n()` on the existing overhead data:

| To detect | n per arm |
|---|---|
| d = 0.8 (large) | **25** |
| d = 0.5 (medium) | **63** |

`aggregate.py` prints this on every run and says plainly when a comparison is underpowered.
