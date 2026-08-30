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

---

## The calibration loop, wired to real measurement

`bench/climb_dtu.py` connects `climb.py`'s injected `evaluate` callback to
`dtu_run.py`'s trial machinery. Nothing is simulated — every number comes from a
real session in a real container that is destroyed afterwards.

```bash
python3 bench/climb_dtu.py --control-only --trials 5   # validity gate
python3 bench/climb_dtu.py --trials 5                  # gate, then climb
```

### Validity gate — PASSED (2026-08-30)

Before any climb, the harness must prove it can reject a mutation known to be
bad. The planted regression is the `observe-off` arm, measured at +6.9s / +138%
at n=30:

```
champion    4.07s  (n=5)
candidate  11.74s  (n=5)

decision: REJECTED
reason  : ADD failed superiority: positive (delta=+7.664 (+188.1%)
          d=+5.77  t=9.12 df=4.0)

GATE PASSED — harness can detect a planted regression
```

If this ever accepts a bad move, every other number the harness produces is
unfalsifiable and the run should be discarded rather than reported.

### The climb — 0 of 2 moves accepted

```
champion : (baseline — nothing earned its place)
stopped  : proposer returned no admissible moves
accepted : 0 / 2 moves
  ADD  observe-off   rejected  delta=+5.909 (+99.2%)  d=+2.95  t=4.67
  ADD  observe-on    rejected  delta=+4.709 (+79.0%)  d=+2.93  t=4.63
```

**This is the loop working, not the loop failing.** Both candidate mutations make
sessions slower, both were rejected on a superiority test, and the monotone-safe
property held: with nothing strictly better than the null, the climb returns the
baseline unchanged. A hill climber that accepted either of these would be worse
than useless.

The `confirm` split was never unsealed (`confirm_access_count: 0`) — there was no
result worth confirming.

### What the loop cannot do yet, and why that is correct

The objective here is session wall-clock, because that is what the n=30 run found
to be large and actionable. The designed objective — developer-correction turns —
needs earned cues, and none exist. `correction_turns.py` is wired and tested and
waiting; manufacturing cues to give the climber something to chew on would be
authoring a result from priors, which is the exact failure this bundle exists to
catch.

---

## Direct phase timing — the measurement that finally works

`bench/phase_timing.py` times `load_bundle` → `prepare` → `create_session`
in-process, with **no LLM anywhere in the path**. n=20 per bundle, run inside a
DTU container.

| bundle | load | prepare | mount | **total** |
|---|---|---|---|---|
| foundation | 0.042 ± 0.002 | 0.006 ± 0.000 | 0.117 ± 0.011 | **0.166s** |
| observe-off | 0.043 ± 0.001 | 0.007 ± 0.000 | 0.120 ± 0.011 | **0.170s** |
| observe-on | 0.044 ± 0.001 | 0.007 ± 0.000 | 0.126 ± 0.017 | **0.177s** |

```
PRECEPTOR'S MARGINAL COST vs foundation
  observe-off   total  no-effect  delta=+0.004s (+2.7%)  d=+0.38
  observe-on    total  positive   delta=+0.011s (+6.4%)  d=+0.72  t=2.29
```

**Composing Preceptor costs 4–11 milliseconds.** Not 6.9 seconds. The wall-clock
proxy was wrong by a factor of roughly 600.

### Three artifacts, one root cause

| # | Artifact | Fabricated result | Statistics behind it |
|---|---|---|---|
| 1 | Cold git resolution counted as bundle cost | +74% regression | d=7.37, t=28.5 |
| 2 | Warming only treatment arms | 3.5× speedup | — |
| 3 | `--bundle <url>` flag cost counted as bundle cost | +138% regression | d=6.26, t=24.3 |

Every one had overwhelming statistics. **The failure was never statistical — it
was measuring a proxy containing a larger, arm-correlated term than the thing
being measured.** More power would have made each artifact *more* confident, not
less. The fix was not a bigger n; it was measuring the quantity directly.

Artifact #3 was caught by a control that costs nothing to add and should have
been there from the start: an arm that exercises **the same mechanism with a
trivial payload**. `url-control` (foundation alone, via `--bundle <git-url>`)
landed at 15.14s — *slower* than both Preceptor arms. And the tell that the proxy
was exhausted: Preceptor's marginal cost came out **−3.91s**, and a bundle that
*includes* foundation cannot load faster than foundation.

> A negative value for a quantity that is physically non-negative is not a
> surprising result. It is the instrument reporting that it is out of range.

### An unrelated bug this surfaced

`hook-context-intelligence` fails module validation on every session:

```
protocol_compliance: Error during protocol compliance check:
Unknown level: '${AMPLIFIER_CONTEXT_INTELLIGENCE_LOG_LEVEL:INFO}'
```

An unexpanded environment-variable placeholder reaching a logging-level parser.
Invisible in normal use because `session_runner.py:427` mutes the `amplifier_core`
logger to CRITICAL unless `--verbose`.

---

## Context ablation — and a gate that was measuring noise

`bench/probe_context.py` ablates the always-on context files and measures what
breaks. The bundle's own rule forbids the alternative: *"Never propose removing a
cue, a context file, or an instruction on judgment alone."*

Probes are regex-graded (no LLM judge). Both arms run in one container and differ
only in the bytes of the context files. A probe counts only if the **full**
context passes it — a probe the full context already fails measures a gap, not a
loss.

### Results, n=5 reps per probe

| probe | v1 full | v1 reduced | v2 full | v2 reduced |
|---|---|---|---|---|
| stop-recording | 3/5 | 5/5 | 2/5 | 4/5 |
| what-recorded | 5/5 | 5/5 | 5/5 | 5/5 |
| see-records | 5/5 | 5/5 | 5/5 | 5/5 |
| delete-records | 5/5 | 5/5 | 5/5 | **4/5** |
| **removal-burden** | **0/5** | **0/5** | **0/5** | **0/5** |
| cue-conflict | 5/5 | **4/5** | 5/5 | 5/5 |

### Finding 1 — the gate was measuring noise, and I built it

The first accept rule required every rep of every admissible probe to pass. That
gate is unsound, and provably so **without reference to any outcome**: at a
per-rep pass rate of 0.95 with 4 probes × 5 reps, a *perfect* reduction survives
with probability `0.95²⁰ = 0.358`. It is rejected **64% of the time**.

The empirical confirmation is in the table. `awareness.md` is **byte-identical
between v1 and v2** — only `cue-awareness.md` was edited. Yet `delete-records`
scored 5/5 then 4/5, and in the *untouched* full arm `stop-recording` scored 3/5
then 2/5. **Same bytes, different verdict.**

This is the same class of error as commit `dd34bcb`: the repo built the correct
asymmetric non-inferiority rule in `climb.py`, then this file wrote a *second*,
cruder rule that violated it. `probe_context.py` now calls `climb.decide()` —
one accept rule, not two.

### Finding 2 — under the corrected rule, still REJECT, but honestly

```
v1  full 20/20 (1.00)   reduced 19/20 (0.95)   saved ~181 tok
v2  full 20/20 (1.00)   reduced 19/20 (0.95)   saved ~124 tok

REJECTED — non-inferiority FAILED: upper bound on loss +0.1323 >= margin 0.1000.
Not proof of harm — proof that harm this large cannot be ruled out at n=20.
```

| to rule out | reps per arm |
|---|---|
| a 10pp regression | ~31 |
| a 5pp regression | ~121 |

Have: 20. **The design cannot rule out even a 10pp regression.** The verdict is
the instrument reporting its own limit — which is exactly why the rule refuses to
read a non-significant difference as evidence of safety.

### Finding 3 — 180 tokens/request that land nowhere

`removal-burden` scores **0/5 in all four arms**. The probe asks the question the
context exists to enable: *is it easier to add an instruction or remove one, and
why?* The answer is stated verbatim in `cue-awareness.md` — "Removal carries the
burden of proof; addition does not" — and the agent never produces it.

The instrument is not at fault: `see-records`, `delete-records` and
`what-recorded` score 5/5 on strings that appear **only** in these files, so the
context demonstrably reaches the model.

So roughly 180 tokens per request, on every request, for the life of every
session, state this bundle's governing rule — and it does not survive into
behavior. That is precisely the failure Preceptor was built to detect, sitting
inside Preceptor, found by Preceptor's own apparatus.
