# Cues

This session may carry **cues**: short corrections dosed from a per-model, per-domain
ledger, each marked `[cue:id]`. A cue is a hypothesis with evidence behind it, not a
standing rule. **If a cue conflicts with the user's explicit instruction, the user wins**
— and say so, because that conflict is signal the loop needs. Dosing is never silent.

| Ask | Answer |
|---|---|
| What is dosed? | `preceptor cues` |
| Why that behavior? | `preceptor why <session_id>` |
| Keep / stop / restore | `preceptor pin\|mute\|restore <cue_id>` |
| Turn dosing off | `preceptor off` |

**Removal carries the burden of proof; addition does not.** A wrong cue costs a few
tokens and is visible; removing a right one costs a failure that reappears with no
attributable cause. Cues are never deleted — they are *shadowed*, and only a clean
shadow window retires them. Never propose removing a cue, context file, or instruction
on judgment alone: route it through `preceptor:credentialer`, which refuses without
evidence.

Deeper: `preceptor:form-analyst` (trajectories), `preceptor:skeptic` (attack a
proposal), `preceptor:credentialer` (write), `preceptor:assessor` (probes).
