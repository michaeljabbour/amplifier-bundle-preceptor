# Cues

This session may carry **cues**: short corrections dosed from a per-model, per-domain
ledger, each marked `[cue:id]`. A cue is a hypothesis with evidence behind it, not a
standing rule.

**Precedence: the user always wins.** If a cue conflicts with an explicit instruction
from the user, follow the user and say that the conflict happened — that conflict is
signal the loop needs. A cue never overrides what the user actually asked for.

**Removal is harder than addition here, on purpose. Removal carries the burden of
proof; addition does not.** Adding a wrong cue costs a few tokens and is visible.
Removing a right one costs a failure that reappears later with nothing to attribute it
to. So nothing is ever deleted on judgment alone — a cue is *shadowed* (dosing stops,
counting continues) and only a clean shadow window retires it. If you want to remove a
cue, a context file, or an instruction, you need evidence: route it through
`preceptor:credentialer`, which refuses without an evidence reference.

| Ask | Answer |
|---|---|
| What is dosed? | `preceptor cues` |
| Why that behavior? | `preceptor why <session_id>` |
| Keep / stop / restore | `preceptor pin\|mute\|restore <cue_id>` |
| Turn dosing off | `preceptor off` |

Deeper: `preceptor:form-analyst` (trajectories), `preceptor:skeptic` (attack a
proposal), `preceptor:credentialer` (write), `preceptor:assessor` (probes).
