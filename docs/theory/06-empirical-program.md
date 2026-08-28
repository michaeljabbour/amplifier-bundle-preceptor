# The Empirical Program

*How Preceptor becomes empirically defensible — and the finding that nearly sinks it.*

Compiled 2026-08-28 from three parallel research passes: ecosystem eval infrastructure,
the external benchmark landscape, and DTU capability limits.

---

## 1. Start with the bad news

The thesis rests on one claim: **static instruction sets decay into overconstraint, so
removal is the missing mechanism.** The evidence offered for it is Anthropic's report that
they cut 80% of the Claude Code system prompt with no eval loss.

Two things about that, both bad.

### 1.1 The Anthropic claim has no methodology

Primary source, verbatim (claude.com/blog/the-new-rules-of-context-engineering-for-claude-5-generation-models,
Thariq Shihipar, 24 Jul 2026):

> "We removed over 80% of Claude Code's system prompt for models like Claude Opus 5 and
> Claude Fable 5 with no measurable loss on our coding evaluations."

No eval names. No task counts. No confidence intervals. No ablation procedure. No sample
sizes. It is an engineering-blog assertion, and this bundle has been treating it as a
result.

### 1.2 The only peer-reviewed instruction-ablation study points the OTHER WAY

**arXiv:2601.20404** — *On the Impact of AGENTS.md Files on the Efficiency of AI Coding
Agents* (Lulla, Mohsenimofidi, Galster, Zhang, Baltes, Treude; Jan 2026, rev. Mar 2026).

10 repositories, 124 pull requests, agents run **with and without** an AGENTS.md file.
That is precisely the ablation design Preceptor claims nobody runs. Result:

| | With AGENTS.md |
|---|---|
| Median runtime | **28.64% lower** |
| Output tokens | **16.58% lower** |
| Task completion | comparable |

**Adding repo-level instructions made agents measurably more efficient.** This is the
strongest published evidence in the area and it cuts against "removal is the missing half."

### 1.3 What honesty requires

The bundle's README currently presents the 80% cut as established fact. It is not. The
correct statement is:

> Whether instruction removal helps is an **open empirical question**. One unpublished
> vendor claim says yes. One peer-reviewed study on a different instruction artifact says
> adding helps. Nobody has run a systematic per-instruction ablation.

That is a weaker claim and a much better project. It converts Preceptor from *a tool
built on an assumption* into *the instrument that settles the question* — and a null or
negative result is then a real contribution rather than a failure.

---

## 2. The reframe

**Do not position Preceptor as "the bundle that makes agents better."**

That frame loses. The effect would be small, expensive to detect, confounded by scaffold
differences, and — per §1.2 — possibly the wrong sign.

**Position Preceptor as the first systematic instruction-ablation instrument.**

The research confirms this gap is real and unclaimed:

| System | Removes instructions? |
|---|---|
| GEPA (ICLR 2026 Oral) | Incidentally — reflective rewrite may be shorter. No delete operator, no length objective. |
| **ACE** (arXiv:2510.04618) | **Actively resists.** Stated design goal is fighting "brevity bias and context collapse" via *grow-and-refine*. |
| DSPy / MIPROv2 | No. Rewrites instructions, selects demos. |
| TextGrad | No. Backpropagated critique edits — additive by construction. |
| PromptBreeder | No. Evolutionary mutation, fitness = task accuracy only. |
| Prompt compression (LLMLingua) | Optimizes token count under output similarity. Never asks if an instruction was load-bearing. |
| Context pruning (SWE-Pruner) | Prunes *retrieved code*, not instructions. Different object. |

> Every optimizer shares one structural bias: fitness is task score and instruction length
> is unconstrained. Under that objective, adding a plausible instruction is free and
> removing a real one is risky, so the search drifts monotonically longer. **An optimizer
> only removes what its objective charges it for keeping.**

Preceptor's contribution is charging for it.

### 2.1 The mechanism is already documented — and it is not token cost

Anthropic's own diagnosis, which is the useful part of that blog post: they found
**conflicting instructions inside a single request** — "leave documentation as appropriate"
from one source colliding with "DO NOT add comments" from the system prompt. The model
resolved it, but spent reasoning on the conflict.

The failure mode is **contradiction cost, not token cost.** That reframes what to measure:
not prompt length, but instruction conflict.

Corroborated independently by **IFBench** (arXiv:2507.02833, Ai2, NeurIPS 2025 D&B), whose
headline finding is that **constraint-following and task-completion trade off against each
other**. A model given more constraints does the main task worse. That is the empirical
mechanism, measured with executable verifiers rather than asserted in a blog post.

**IFBench is the cheapest external benchmark that directly probes Preceptor's mechanism:**
58 programmatically-verifiable out-of-domain constraints × 300 held-out prompts, executable
verification functions, no LLM judge, runs locally.

---

## 3. What to measure, and the trap to avoid

### 3.1 Do NOT build an LLM-judged trajectory metric

**arXiv:2608.22960** — *What Process Evaluation of Coding Agents Actually Measures*
(He et al., 24 Aug 2026) — demonstrates that **full-trace LLM judges exhibit systematic
collider bias**: shown the whole trace, a judge scores *semantic relevance*, not *causal
contribution*. It picks the step that looks decisive in hindsight, not the step that
changed the outcome.

The obvious way to score trajectory quality is therefore measuring the wrong thing from
day one. Their alternative (SCAE) is replay/intervention-based over a structural causal
model — real, but 4 days old with no released harness.

**Consequence for this bundle:** the `assessor` agent must never grade a trajectory by
reading it. Grades come from executable rubrics. This is already the design
(`probes/*/rubric.sh`, exit code IS the grade) — the research says keep it and never
soften it.

### 3.2 The metric nobody has: developer-correction turns

`amplifier-bundle-evaluation` ships an **AI User** that drives multi-turn sessions. Its
system prompt (`ai_user/ai_user.py:122-129`) instructs it, verbatim:

> "The agent will often return before completing the scenario. It might ask a clarifying
> question, stop after a single mode-confirmation gate, pause for direction, or offer
> options without picking one. In every such case, send a short follow-up that nudges it
> to keep going ('go ahead', 'yes', 'proceed', or a brief direct answer)"

**That is a scripted developer issuing corrections, and nothing counts them.** The data is
already produced and already extracted — `ai_user.json` and `extraction/*/transcript.jsonl`
— on every trial anyone has ever run.

An exhaustive search across evaluation, ergonomics, feedback, behavioral-plasticity,
context-intelligence and the survey bundle found **zero implementations** of a correction
metric. The closest named artifact, `context-intelligence/modules/tool-user-repetition/`,
contains only a stale `__pycache__` and no source.

> The metric is cheap precisely because the nudge policy is already written down as an
> instruction. A rule the agent is *told* to follow is a rule you can *count* against —
> that system prompt is simultaneously the behavior spec and the labeling function.
> Instrument at the seam where a policy is already explicit, not where it is implicit in
> behavior.

**Correction-turn rate is the primary outcome for this program:** free, continuous, needs
no authored rubric per domain, hard to game, and it is what a developer actually feels.

### 3.3 The full metric set

| Metric | Source | Judge-free? |
|---|---|---|
| **Correction turns per task** | `transcript.jsonl`, AI User follow-ups | yes |
| Task success | executable rubric, exit code | yes |
| Root-context tokens vs. session-tree total | `events.jsonl` via `compare.py` root picker | yes |
| Tool calls, retries, re-reads | `events.jsonl` | yes |
| Wall clock | trial `state.json` | yes |
| Instruction-conflict incidence | IFBench-style verifiers | yes |

Every one is executable. No judge anywhere in the measurement path.

---

## 4. Which benchmarks, and the honest cost

| Benchmark | Tasks | Scoring | Verdict for this program |
|---|---|---|---|
| **IFBench** | 58 constraints × 300 prompts | executable verifiers | **Run first.** Directly probes the constraint/completion tradeoff. Cheap, local, no judge. |
| **Terminal-Bench 2.0** (Harbor) | 89 | executable tests in-container | **Run second.** k=5 and CIs are *mandatory* on submission; CIs already ±2%. Most runnable serious benchmark. |
| SWE-bench Verified | 500 | executable tests | Ticket of entry, saturated. ~$100–400 and 15k–40k API calls **per arm**. Use the **bash-only split** or the number is scaffold noise. |
| SWE-Bench Pro | 731 public | executable tests | Contamination-resistant, publishes CIs. Top public: 61.5% ±3.1. Better science, higher cost. |
| ProgramBench | — | executable | **All public models score 0%.** Zero discriminating power. Skip. |

**Precedent that harness changes produce large effects:** arXiv:2608.26218 (*Same Model,
Different Harness*, 26 Aug 2026) held model and task fixed, changed only context-management
policy, and moved mean per-task fail-to-pass from **28% → 49% across 169 Verified tasks**.
Their conclusion: *"coding-agent evaluations should treat the model and harness together as
the tested solver."* Harness-layer effects are detectable and large. That is the existence
proof this program needs.

---

## 5. The bootstrap problem, solved

Preceptor cannot measure benefit because no cues exist. Cues require observed failures.
Observed failures require sessions. **The AI User generates them.**

```
1. RUN        27 existing tasks × N trials with observe-on, AI User driving
                 -> real multi-turn sessions, real failures, real corrections
2. HARVEST    every AI-User correction turn is a LABELED FAILURE
                 -> the nudge says what the agent should have done
3. PROPOSE    form-analyst reads observations + correction turns
                 -> cue candidates traceable to specific corrections
4. VERIFY     skeptic attacks each; credentialer refuses unresolvable evidence
5. ABLATE     assessor runs whole-set-first ablation on held-out tasks
```

Step 2 is the unlock. A correction turn is not merely a metric — **it is a self-labeling
failure**: the developer's nudge states the correction, so the cue writes itself from
evidence rather than from priors. This is the honest bootstrap the bundle needed, and it
falls out of infrastructure that already exists.

**Gate probes and grade probes stay disjoint.** Tasks used to harvest cues must never be
used to evaluate them. A system that grades itself on its own gate is unfalsifiable, and
there is already a test asserting the intersection is empty.

---

## 6. Experimental design

### 6.1 Arms

The A/B lever in `amplifier-bundle-evaluation` is `agents/<id>/install.yaml` — two agent
directories differing only in the `amplifier bundle add` line.

| Arm | Instruction layer | Tests |
|---|---|---|
| `baseline` | foundation only | control |
| `preceptor-off` | + preceptor, cues disabled | cost of loading |
| `preceptor-on` | + preceptor, earned cues dosed | **the claim** |
| `sham` | + cues earned on a *different* model/domain, matched count and length | **is "earned" real?** |
| `frozen` | + a one-time human profile, never updated | **is *continuous* worth anything?** |
| `bloat` | + N plausible unearned instructions | **does removal help at all?** (tests §1.2 head-on) |

`sham` and `frozen` are the arms that can embarrass this project, which is why they are
non-negotiable. If `preceptor-on ≈ sham`, "earned" and "per-model" mean nothing and this is
an expensive generic prompt. If `preceptor-on ≈ frozen`, the continuous loop is unjustified
and the right product is a batch pass.

`bloat` is new, added because of §1.2. It is the arm that tests the thesis in the direction
the literature says it might fail.

### 6.2 Power

`bench/run.py` already learned this the hard way: at n=5, d=1.16 was **not** significant
(Welch t=1.84, df≈6.9, p≈0.11). Pre-registered requirements:

- **n ≥ 30 per arm** for a small-to-medium effect
- Report mean **and** spread, always
- Pre-register minimum detectable effect **before** running
- `positive` / `no-effect` / `inconclusive` — never a bare pass/fail
- `inconclusive` keeps the cue and means *keep looking*, never *no effect*

### 6.3 Reporting

Follow **Terminal-Bench's submission protocol** as the house standard: k=5 runs minimum,
confidence intervals mandatory, no modification of timeouts or resources between arms.

Follow **Artificial Analysis's harness-comparison shape**: hold the model constant, vary
only the instruction layer, and report tokens / cost / turns *alongside* score rather than
score alone.

---

## 7. DTU capacity — measured, not assumed

| Resource | Value | Note |
|---|---|---|
| Host | 18 cores, 128 GiB, 1.3 TiB free | **massively underused** |
| Colima `resolve` VM | **4 CPU, 8 GiB, 60 GiB** | the real ceiling |
| Currently running | **14 live DTUs**, not ours | ~1.8 GB RSS, 18 GiB ZFS |
| Free in VM | ~4.8 GB RAM, ~34 GB disk | |
| **Practical concurrency now** | **2–4 agent trials** | 4 vCPU already at load 1.00 |

**We are not restarting Colima.** `colima start resolve --cpu 12 --memory 64 --disk 300`
would widen the ceiling dramatically, but it destroys 14 running environments belonging to
other work. That is a decision for their owner, not a benchmark's convenience.

### 7.1 The golden-image path (the affordability unlock)

DTU's CLI has no snapshot/clone. Raw Incus does, and the storage driver is **ZFS** — DTU
instances are *already* ZFS clones of image `@readonly` snapshots (an `amp-app-cli-tui`
instance measures 237 MB physical against 701 MB logical).

```bash
# provision ONCE, without API keys baked in
amplifier-digital-twin launch ./exp-base.yaml --name exp-golden
incus stop exp-golden
incus publish exp-golden --alias preceptor-warm --compression none
```

Then in the trial profile:

```yaml
base:
  image: local:preceptor-warm
provision:
  setup_cmds: []          # nothing left to install — cannot time out
```

This keeps the entire supported DTU CLI (`exec`, `file-pull`, `destroy`, readiness,
passthrough) while removing the dominant per-trial cost. When a system's fast path is
already copy-on-write, the expensive-looking operation (clone 60 containers) is the cheap
one; the expensive one is what you'd assume is free — re-running `apt-get` 60 times.

### 7.2 Traps that will break a long batch

| Trap | Defense |
|---|---|
| `exec` defaults to a **600 s timeout** and raises | always `--timeout none` for agent runs |
| `destroy` calls delete with **`force=False`**; stop swallows errors → orphans | `destroy \|\| incus delete --force` |
| `incus launch` takes **130–170 s at 30+ containers** vs. a 120 s default | `AMPLIFIER_DTU_INCUS_LAUNCH_TIMEOUT_SECONDS=600` |
| `file-pull -r` spawns **one subprocess per file**; 120 s default | tar in-container, pull one file |
| API keys land in **plaintext** at `/etc/profile.d/dtu-env.sh` → baked into published images | provision golden *without* keys; inject per-trial |
| `list` is machine-wide — returns the 14 unrelated DTUs | filter on own name prefix; **never reap by iterating `list`** |
| ZFS `default/deleted` holds 1.9 GiB unreclaimed; deletion is deferred | abort batch below an 8 GiB free floor |
| `url_rewrites` → mitmproxy **destroys SSE/token streaming** | no rewrites for trajectory work |

---

## 8. Build vs. reuse

| Need | Decision |
|---|---|
| Trial lifecycle, DTU isolation, retry/cancel | **reuse** `amplifier_evaluation.harness` |
| A/B arm mechanism | **reuse** — two `agents/*/install.yaml` |
| Multi-turn developer simulation | **reuse** `AIUser` |
| Root-vs-total token accounting | **reuse** `examples/01-explorer-removal/compare.py` |
| SWE-bench task generation at scale | **reuse the sampler**, loop it |
| Statistical verdicts (d + Welch + inconclusive) | **already built** — `bench/verdict.py` |
| Executable rubrics (exit code = grade) | **already built** — `probes/*/rubric.sh` |
| **LLM-as-judge grader** | **REJECT** — injects variance into a small effect; see §3.1 |
| **Correction-turn metric** | **BUILD** — nothing exists |
| **Cross-trial aggregation to arm statistics** | **BUILD** — only per-trial `state.json` ships |

Take the evaluation bundle's *lifecycle*; reject its *grader*.

---

## 9. What would make this genuinely awesome

Ranked by leverage:

1. **Publish the ablation curve nobody has.** Instruction count on x, task success and
   correction rate on y, per model. That single figure is the contribution — and it is
   equally publishable whether the slope is negative, flat, or positive.
2. **Ship the correction-turn metric as a standalone tool.** It is ~150 lines over
   artifacts every eval run already produces, it needs no judge, and it measures something
   the whole field currently cannot.
3. **Run IFBench with and without an instruction layer.** Directly tests the mechanism
   (constraint/completion tradeoff) at low cost with executable verifiers.
4. **Replicate arXiv:2601.20404 in the opposite direction.** They showed adding AGENTS.md
   helps. Run the same design on *system-prompt* instructions. If both hold, the finding is
   that the artifact type matters more than the volume — which is more interesting than
   either paper alone.
5. **Terminal-Bench 2.0 with k=5**, arms as §6.1. The credibility number.

---

## 10. The honest position

Preceptor today is a **well-built instrument measuring an unproven hypothesis**, and the
one peer-reviewed study in the area points the other way.

That is a good place to be, provided the bundle says so. The value is not in being right
about removal. It is in being the only apparatus that can tell you — and in being willing
to publish the answer when it comes back negative.

The autonomy lock, the shadow window, the `inconclusive` verdict, the refusal to print a
benefit number with no earned cues: all of that is the same discipline. This document is
that discipline applied to the thesis itself.
