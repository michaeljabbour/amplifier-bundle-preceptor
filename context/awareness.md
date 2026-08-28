# Preceptor observation

A trajectory observer may be recording **structural** form signals from this session:
which tools ran in what order, retries, repeated reads, error recovery, run boundaries.
It records no message content and no file contents. It never gates or modifies anything.

Recording is **off unless explicitly enabled**. Records live under
`~/.amplifier/projects/{project}/preceptor/observations/` and expire on a retention clock.

| Ask | Answer |
|---|---|
| What is being recorded? | `preceptor status` |
| Show me my own records | `preceptor observations --mine` |
| Stop recording | set `enabled: false` in `~/.amplifier/settings.yaml` |
| Delete what was recorded | `preceptor forget --since <date>` |

Observation records are raw and uninterpreted by design. Naming a signal
(`arbitration`, `retry-loop`) is a judgment call and belongs to
`preceptor:form-analyst`, not to the hook.
