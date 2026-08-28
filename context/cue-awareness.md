# Cues

This session may carry **cues**: short corrections dosed from a per-model, per-domain
ledger, each marked `[cue:id]`. A cue is a hypothesis with evidence behind it, not a
standing rule. If a cue conflicts with the user's explicit instruction, the user wins —
and say so, because that conflict is a signal the loop needs.

When cues are active you will see a one-line receipt at session start. Dosing is never
silent.

| Ask | Answer |
|---|---|
| What is dosed right now? | `preceptor cues` |
| Why did it behave that way? | `preceptor why <session_id>` |
| Keep this cue permanently | `preceptor pin <cue_id>` |
| Stop this cue | `preceptor mute <cue_id \| domain \| all>` |
| Bring back something removed | `preceptor restore <cue_id>` |
| Turn dosing off entirely | `preceptor off` |

## The rule that governs this bundle

**Removal carries the burden of proof; addition does not.** Adding a wrong cue costs a few
tokens and is visible. Removing a right one costs a failure that reappears later with no
attributable cause. So a cue is never deleted — it is *shadowed*: dosing stops, counting
continues, and only a clean shadow window retires it.

Never propose removing a cue, a context file, or an instruction on judgment alone. Route it
through `preceptor:credentialer`, which will refuse without an evidence reference.

Delegate anything deeper to `preceptor:form-analyst` (read trajectories),
`preceptor:skeptic` (attack a proposal), `preceptor:credentialer` (write the ledger),
or `preceptor:assessor` (run probes).
