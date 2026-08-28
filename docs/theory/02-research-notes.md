# Research Notes: The Claude 5 Context Shift

*Compiled August 28, 2026*

Sources:

- [The new rules of context engineering for Claude 5 generation models](https://claude.com/blog/the-new-rules-of-context-engineering-for-claude-5-generation-models), Thariq Shihipar, July 24, 2026
- [A harness for every task: dynamic workflows in Claude Code](https://claude.com/blog/a-harness-for-every-task-dynamic-workflows-in-claude-code), Thariq Shihipar and Sid Bidasaria, June 2, 2026
- [Amplifier Bundle Authoring Guide](https://github.com/microsoft/amplifier-foundation/blob/main/docs/BUNDLE_GUIDE.md), microsoft/amplifier-foundation
- Background: [Effective context engineering for AI agents](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents) and the [Fable field guide](https://claude.com/blog/a-field-guide-to-claude-fable-finding-your-unknowns)

## 1. The new rules post

Headline result: the Claude Code team removed over 80% of the system prompt for Claude 5 generation models (Opus 5, Fable 5) with no measurable loss on their coding evals. Their diagnosis: guardrails written to keep older models from worst cases now overconstrain capable ones. Their own internal transcripts showed single requests carrying contradictory guidance about documentation as system prompt, skills, and user intent collided, with the model spending reasoning to arbitrate.

The six shifts, with the substance behind each:

1. **Rules become judgment.** The old prompt banned comments and planning documents outright. The new prompt tells the model to write code that reads like the surrounding code, matching comment density, naming, and idiom. Hard rules become principles wherever a principle suffices.
2. **Examples become interfaces.** Worked examples now constrain the model's exploration space. Leverage moved to schema design: a todo status enum of pending, in_progress, and completed teaches usage on its own, and a one-line constraint about keeping a single item in progress defines the requested behavior.
3. **Front-loading becomes progressive disclosure.** Code review and verification moved into skills the agent loads selectively. Some tools defer entirely: the agent must look up their full definitions through ToolSearch before use. The same logic applies to CLAUDE.md, which they recommend restructuring as a tree of files loaded at the right moment.
4. **Repetition becomes single-sourcing.** Instructions about a tool live once, in the tool description, and get deleted from the system prompt.
5. **Manual memory becomes auto-memory.** The old hotkey workflow for writing to CLAUDE.md gives way to automatic saves of relevant context.
6. **Simple specs become rich references.** A plan can be an HTML artifact. A spec can be a test suite or a function in another codebase to port. Rubrics let verifier agents check work against your taste.

Their layer model: the system prompt carries product identity; CLAUDE.md stays lightweight and spends tokens on codebase gotchas rather than anything inferable from the repo; skills encode opinions particular to a team; references prefer code over prose, since an HTML mockup outperforms a description or a screenshot. They shipped a `/doctor` command that audits and rightsizes skills and CLAUDE.md files.

**Through the preceptor frame:** everything shipped is better curriculum. The loop that produced it stayed internal: engineers read transcripts, spotted the arbitration, deleted, and gated on evals. `/doctor` is the closest productized piece, and it is a checkup by appointment rather than a resident coach. Their own suggested workflow, mining 50 sessions for repeated corrections and distilling them into CLAUDE.md rules, is the preceptor in batch mode, run when a user thinks to run it.

## 2. Dynamic workflows

Claude Code now writes its own harness on the fly: a JavaScript file with functions for spawning and coordinating subagents, with per-agent model selection and worktree isolation. The post names the failure modes this addresses, and the naming is useful vocabulary: **agentic laziness** (declaring done after partial progress), **self-preferential bias** (favoring one's own findings when judging), and **goal drift** (lossy fidelity across compaction). The composable patterns: classify-and-act, fan-out-and-synthesize, adversarial verification, generate-and-filter, tournament, loop-until-done. For rule adherence they suggest one verifier agent per rule plus a skeptic persona to hold down false positives. Workflows take token budgets, save with a keystroke, and distribute inside skills. Bun's Zig-to-Rust rewrite ran on this machinery.

**Through the frame:** the offline muscle the preceptor needs already exists. Fan-out over sessions, adversarial verification of candidate rules, tournament selection: all of it. Missing are the two ends of the loop: a standing observation substrate that captures form continuously rather than on request, and a fade discipline that removes cues with evidence rather than letting them accrete.

## 3. The Amplifier bundle system

Inventory of the constructs the design builds on, from the Bundle Authoring Guide:

- A **bundle** is a composable configuration unit producing a mount plan for a session: tools, agents, hooks, providers, instructions, spawn policy. Configuration, not a Python package.
- The **thin bundle pattern**: inherit from `foundation`, declare only what you uniquely add. `anchors` is the runtime default you run; `foundation` is the base you build on.
- The **behavior pattern**: the reusable capability lives in `behaviors/*.yaml` (agents plus context, optionally tools and hooks), and the root bundle includes its own behavior to make it reachable.
- **Context semantics**: `context.include` accumulates and propagates to every including bundle, while `@mentions` bind to one instruction and get replaced during composition. The two are not interchangeable.
- **The 500-token policy**: files in a behavior's `context.include` above 500 tokens need justification, and above 1,000 they must move. This rule exists because real bundles shipped always-on context that cost 15 to 20 thousand tokens per session, cut back by a manual migration in May 2026. Direct evidence for the scar-tissue claim in the thesis.
- **Context sinks**: heavy documentation lives as `@mentions` inside an expert agent's body, loading only when that agent spawns. **Soft references** (a path without the `@`) load on demand via `read_file`.
- **Hooks** are the observability and control mechanism. **Policy behaviors** are app-composed, root-session-only hooks that check `parent_id`.
- **Spawn policy** controls tool inheritance for spawned agents (`exclude_tools` or an explicit allow list), and inline agent definitions can scope tools to a single agent.
- **Recipes** (amplifier-bundle-recipes) give declarative multi-step orchestration, the native analog of dynamic workflows.
- **App-level injection**: providers, keys, and environment-specific paths come from app settings at runtime, never from the bundle. Secrets stay in the environment.
- Module contract: `mount()` must call `coordinator.mount()`, and `on_session_ready()` fires once after full composition for cross-module wiring.

## 4. What the frame predicts

Static guidance decays at the rate models improve, so any fixed instruction sheet written today overconstrains the model shipping next spring. Systems with a fading mechanism track the frontier; systems without one repeat the cycle of accretion and periodic manual surgery that both Anthropic and the Amplifier ecosystem have now demonstrated. The generation-specificity of the new rules is the sharpest version of the prediction: guidance tuned to Claude 5 class models is wrong for weaker models today, which makes per-model credentials a requirement for any runtime serving more than one family, and an opening for the platform layer that maintains them.
