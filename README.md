<div align="center">

# Preceptor

**Every context system has an ADD mechanism. Almost none has a REMOVE mechanism.**

*So context accretes until a human notices and performs surgery.*
*Preceptor is the missing half: removal, standing and evidence-gated.*

`amplifier-core` + `amplifier-foundation` only · no sibling bundles · 54 tests

</div>

---

## The evidence this is real

Anthropic removed **over 80% of the Claude Code system prompt** for Claude 5 generation
models and measured no loss on their coding evals. The guardrails that kept a 2024 model
from writing junk were, by 2026, fighting the model's own judgment — and the model was
paying a reasoning tax to arbitrate between instructions that disagreed.

The Amplifier ecosystem shipped bundles whose always-on context reached **15–20k tokens per
session** before a manual migration cut it back.

Both were rescues. A human happened to look. Neither was a mechanism — and the next
generation of scaffolding is already accreting behind them.

## The loop

![The Preceptor loop](docs/diagrams/loop.svg)

Watch real work. Propose a correction only from a failure that actually happened. Prove it
helps before it stays. **Then keep proving it** — and when it stops earning its place, take
it out and record why.

## The asymmetry everything else gets backwards

Most systems put the heavy evidentiary machinery on *entry* and treat removal as a reward
for good behavior. That is exactly inverted:

|  | Adding a wrong cue | Removing a right one |
|---|---|---|
| **Cost** | ~40 tokens | A failure that returns weeks later |
| **Visible?** | Yes — you see the behavior | **No — absence is invisible** |
| **You experience it as** | "why is it doing that?" | "the model got worse" |
| **Reversible?** | Trivially | In principle. Not in practice. |

So in Preceptor, **removal carries the burden of proof and addition does not.** Nothing is
ever hard-deleted. A cue is *shadowed* — dosing stops, counting continues — and only a clean
window retires it. If a violation reappears, the cue restores itself and pins.

![Cue lifecycle](docs/diagrams/lifecycle.svg)

The ratio of those restores to retirement attempts — **`false_fade_rate`** — is the system's
own trustworthiness metric. It is a gate, not a report: autonomous removal stays locked until
the rate is measured below 10% over at least 40 attempts, and it re-locks by itself if the
rate climbs.

## Quickstart

Start by watching. That is not ceremony — it is the thesis applied to the bundle's own
rollout.

```bash
amplifier run --bundle 'git+https://github.com/michaeljabbour/amplifier-bundle-preceptor@main#subdirectory=bundles/observe-only.yaml'
```

That bundle **records nothing.** The observer ships `enabled: false`, so the command above
verifies the bundle loads and does no more. Recording starts only when you choose the bundle
whose name says so:

```bash
amplifier run --bundle 'git+https://github.com/michaeljabbour/amplifier-bundle-preceptor@main#subdirectory=bundles/observe-on.yaml'
```

Picking that bundle *is* the consent act. There is deliberately no settings-file stanza —
an earlier draft documented one, a Digital Twin run proved it inert (no records, no error,
no way to tell which), and a consent control that fails silently is worse than none.

Run it for a couple of weeks. Read what it saw. *Then* decide whether the rest is warranted:

```bash
amplifier run --bundle git+https://github.com/michaeljabbour/amplifier-bundle-preceptor@main
```

## What you actually see

Dosing is never silent. Every session with active cues opens with a receipt:

```
preceptor: 3 cue(s) active [cue-017, cue-022, cue-031] · claude-opus-5/python-implementation · `preceptor cues`
```

| Ask | Command |
|---|---|
| What's dosed right now? | `preceptor cues` |
| **Why did it do that?** | `preceptor why <session_id>` |
| What's being recorded about me? | `preceptor observations --mine` |
| Keep this one forever | `preceptor pin <cue_id>` |
| Stop this one | `preceptor mute <cue_id \| domain \| all>` |
| Bring back something removed | `preceptor restore <cue_id>` |
| Off | `preceptor off` |
| Delete my records | `preceptor forget --since <date>` |

`why` reads an **immutable per-session manifest**, not the live ledger — so it still returns
the exact text that was dosed even after that cue has been retired and the ledger has moved
on. Without that, "why did it do that last Tuesday?" is unanswerable by construction.

## Architecture

![Bundle architecture](docs/diagrams/architecture.svg)

Two entry points. One behavior chain — `preceptor.yaml` *includes* the observer rather than
duplicating it. Three local modules, no sibling bundles. Per-agent tool scoping means
`credentialer` is the only agent that can write the ledger, and that is enforced by
frontmatter, not by asking nicely in a prompt.

| Piece | Does |
|---|---|
| `hooks-trajectory-observer` | 13 kernel events → buffered, structural records. Priority 200. Never gates. |
| `hooks-cue-injector` | Doses on `provider:request`, priority 20, in its own labelled block. |
| `tool-preceptor` | The ledger, the promote/retire gates, the autonomy lock. |
| `form-analyst` · `skeptic` · `credentialer` · `assessor` | Propose · attack · record · measure. |

## Privacy, in one paragraph

The observer records **structure, not content**: which tools ran in what order, a SHA-256 of
the tool input (never the input), success flags, run boundaries. No message text, no file
contents, no error bodies, **no free-text field of any kind** — the original design had one
and it was removed, because a prose field derived from session content eventually contains
business logic, customer data, and a pasted credential. Records are local, expire on a
90-day clock, and are readable and deletable by the person they are about. See
[`docs/CONSENT.md`](docs/CONSENT.md).

## Ideas worth trying

The mechanism is more general than the bundle. If you're building on this:

- **Point it at the highest-signal event first.** `provider:tool_sequence_repaired` fires
  when a provider had to repair a malformed tool-call sequence the model produced. That is a
  pure model-form defect, already classified by the provider, requiring no judgment from you.
  It is the best cue candidate on the whole event surface and almost nobody looks at it.
- **Ablate the whole set before any single cue.** Cues interact. One large effect is
  measurable; N small ones drown in sampling noise. Anthropic's 80% cut *was* a whole-set
  ablation — the only version of this experiment anyone has run at scale, and it worked.
- **Prefer the correction turn to the probe.** How often the human says *"no, do X instead"*
  is free, continuous, hard to game, and needs no authored rubric per domain. Use probes to
  gate mutations; use correction rate as the standing signal.
- **Fingerprint the environment, not just the model.** The model is frozen. What actually
  moves is your codebase, your dependencies, your task mix — so a cue retired under one
  environment is not evidence about a different one. Invalidate on fingerprint change rather
  than waiting for the failure to recur on a user.
- **Route the learning to the right home.** A codebase gotcha belongs in project context; a
  procedure belongs in a skill; a preference belongs in memory. A model-independent fact in a
  per-model ledger will never fade correctly, because its necessity has nothing to do with the
  model.
- **Apply it to your own repo.** The 500-token context policy, the "does this earn its
  tokens?" question, the refusal to delete without evidence — those are the same discipline
  pointed inward. This repo's [`AGENTS.md`](AGENTS.md) does exactly that.

## Status — honest about what is and isn't proven

This ships **instrumentation before autonomy**, deliberately. The alternative is authoring a
cue taxonomy from priors against zero evidence, which is precisely the failure the bundle
exists to catch.

| Stage | State | Gate to the next stage |
|---|---|---|
| **v0 — observe** | Working | Detector calibrated against hand-labeled ground truth; precision/recall published |
| **v1 — dose, human-approved** | Working, **locked** | One real cue proven to retire on evidence |
| **v2 — autonomous** | Locked | `false_fade_rate < 0.10` over ≥ 40 attempts |

Things this does **not** yet claim: that earned per-model cues beat generic ones; that a
continuous loop beats a one-time human pass. [`docs/theory/05-expert-review.md`](docs/theory/05-expert-review.md)
contains the experiment designed to embarrass this project if those claims are false,
including the sham-cue arm that tests whether "earned" means anything at all.

## Docs

| | |
|---|---|
| [`docs/theory/01-preceptor-thesis.md`](docs/theory/01-preceptor-thesis.md) | The argument |
| [`docs/theory/05-expert-review.md`](docs/theory/05-expert-review.md) | Five specialist reviews, the defects found, what changed |
| [`docs/AUTONOMY.md`](docs/AUTONOMY.md) | Why the lock exists and how it opens |
| [`docs/CONSENT.md`](docs/CONSENT.md) | What is recorded, what never is, and your controls |
| [`context/methodology/cue-lifecycle.md`](context/methodology/cue-lifecycle.md) | The state machine and every gate |
| [`context/methodology/evidence-standards.md`](context/methodology/evidence-standards.md) | What counts as evidence, and the statistical bar |
| [`AGENTS.md`](AGENTS.md) | Repo conventions + hard-won facts about the event surface |

---

<div align="center">
<sub>Diagrams are generated: <code>dot -Tsvg docs/diagrams/&lt;name&gt;.dot -o docs/diagrams/&lt;name&gt;.svg</code></sub>
</div>
