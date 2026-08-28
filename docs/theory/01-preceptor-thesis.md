# Preceptor: Why Context Engineering Needs a Feedback Loop

*MJ, August 28, 2026*

Watch a good trainer work. A trainee walks in and the trainer does not open with a demonstration. The trainer says "show me your squat," watches three reps, and only then speaks. The first cue is one sentence, delivered at the bottom of the movement where it applies. The manual never comes out. Over weeks the trainer says less, because the trainee needs less, and eventually the trainer signs off on a competence that was observed rep by rep, not assumed from the intake form.

Now look at how we engineer context for AI agents. We write the complete instruction set before the model generates a single token. We ship it identically to every session regardless of what the model has already shown it can do. We revise it when an engineer finds time to read transcripts, which in practice means once per model generation. The loop that a mediocre trainer runs continuously, we run manually and rarely.

## The proof the scaffolding was dead weight

Anthropic's July 2026 guidance makes the case for me. Their team removed over 80% of Claude Code's system prompt for Claude 5 generation models and measured no loss on coding evals. Reading their own transcripts, they found single requests carrying contradictory instructions as system prompt, skills, and user intent collided, and the model paying a reasoning tax to arbitrate. The rules that kept a 2024 model from writing junk comments now fight a 2026 model's own judgment.

Their fix is a better instruction sheet: principles over rules, expressive tool schemas over examples, progressive disclosure over front-loading. All correct. But notice who performed the improvement. Humans read the transcripts. Humans noticed the arbitration. Humans deleted, and evals gated the deletion. The trainer existed, worked well, and stayed in the building. The product shipped the curriculum without the coach.

## Form, not just outcome

Evals judge whether the weight went up. A trainer watches form, because the compensation pattern that clears 135 pounds is the same one that tears something at 225. The agent equivalent of form is the trajectory: reasoning tokens, tool-call sequences, retry loops, re-reads of the same file, edit diffs, the visible moments where output wrestles with two instructions that disagree. Outcome tells you a task failed. Form tells you why: wrong decomposition, missing knowledge, or a prompt fighting the model's own judgment. Those three failures want three different interventions, and outcome metrics cannot tell them apart.

## Credentials, earned

The output of sustained observation is a credential: a per-model, per-domain profile of where this model actually needs scaffolding, with every entry linked to the sessions that justify it. An authored profile restates the author's priors. An earned profile records what happened. The distinction matters most at the moment of deletion, because "I believe this rule is obsolete" and "this rule went unviolated across 40 observed opportunities and evals stayed flat without it" carry different weight with anyone who has to trust the system.

## Four primitives

The trainer decomposes into four mechanisms, none exotic:

1. **An observer** that runs off the hot path, reading trajectories and emitting structured form notes. It never gates, never intervenes, never adds latency.
2. **A cue compiler** that doses context: the smallest intervention that changes behavior, placed at the point of the relevant action rather than the top of the prompt.
3. **A fading policy.** A new cue enters as a hypothesis and earns tenure only when the observed behavior changes and results improve. Each active cue then carries counters and a decay schedule. A cue that stops firing becomes a removal candidate, an eval run with and without it settles the question, and a flat result licenses deletion. Anthropic's 80% cut was exactly this test, run once by hand.
4. **Assessment probes**: cheap canary tasks with executable rubrics, run on first contact with a new model or domain. Watch before you program.

The economics favor the loop. Overconstraint taxes every request at inference time, in reasoning tokens spent on arbitration. Observation amortizes offline, in batch, on cheap models.

## The skipped step

Session-mining prompts already exist; Anthropic themselves suggest mining 50 sessions for repeated corrections and distilling rules. That is the trainer in batch mode, user-initiated, retrospective. Optimizer research (agentic context engineering, DSPy-family systems like GEPA) closes a loop on outcome signals, which is judging the lift without watching the form. Fading is what everyone skips, because removal feels dangerous and accretion feels safe. So context only grows scar tissue. Amplifier's own ecosystem shipped bundles whose always-on context reached 15 to 20 thousand tokens per session before a manual migration in May 2026 cut it back. Same shape as Anthropic's story: context accretes until a human performs surgery.

## The name

Medicine already runs this loop and named it. A clinical preceptor watches a resident reason through a live case before offering a word, probes for the evidence behind the plan, teaches one general rule at the moment it applies, and signs off competence a case at a time. The hospital then grants privileges per procedure from that documented record, and supervision steps down the entrustment scale as trust is earned. So the system is called Preceptor: its ledger grants privileges, its baseline probes are boards, its batch pass is chart review, and its fading discipline is entrustment. The gym gave me the shape. The clinic gives it the rigor and the vocabulary.

## Why this belongs in the platform layer

Anthropic ships one model family and can prune globally. A runtime fronting Anthropic, OpenAI, Azure, and local models cannot, because the scaffold the strongest model has outgrown is the scaffold the weakest model still requires. Per-model credentials are the only coherent answer, and a credential earned from observation, versioned, and portable across harnesses becomes a platform asset. The preceptor belongs below any single product, in the runtime that serves them all.
