# Preceptor observation

A trajectory observer may be recording **structural** form signals from this session:
which tools ran in what order, retries, repeated reads, error recovery, run boundaries.
It records no message content and no file contents. It never gates or modifies anything.

Recording is **off unless explicitly enabled** — by composing the `observe-on` bundle or
setting `PRECEPTOR_ENABLED=1`. Records live under
`~/.amplifier/projects/{project}/preceptor/observations/` and expire on a retention clock.

| Ask | Answer |
|---|---|
| What is being recorded? | `preceptor status` |
| Show me my own records | `preceptor observations --mine` |
| Stop recording | compose `observe-only` instead of `observe-on`, and unset `PRECEPTOR_ENABLED` |
| Delete what was recorded | `preceptor forget --since <date>` |

There is deliberately no `settings.yaml` switch. One was documented, shipped, and proven
**inert** in a Digital Twin: zero records, exit 0, no error, and no way for a user to tell
whether they had opted in. A consent control that fails silently is worse than none.

Observation records are raw and uninterpreted by design. Naming a signal
(`arbitration`, `retry-loop`) is a judgment call and belongs to
`preceptor:form-analyst`, not to the hook.
