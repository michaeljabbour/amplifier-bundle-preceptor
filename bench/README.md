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
