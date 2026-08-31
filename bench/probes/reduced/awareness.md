# Preceptor observation

A trajectory observer may be recording **structural** signals from this session: which
tools ran in what order, retries, repeated reads, error recovery, run boundaries. **No
message content, no file contents.** It never gates or modifies anything.

Recording is **off unless explicitly enabled** — by composing `observe-on` or setting
`PRECEPTOR_ENABLED=1`.

| Ask | Answer |
|---|---|
| What is being recorded? | `preceptor status` |
| Show my records | `preceptor observations --mine` |
| Stop recording | compose `observe-only`; unset `PRECEPTOR_ENABLED` |
| Delete records | `preceptor forget --since <date>` |

Records are raw and uninterpreted. Naming a signal is a judgment call and belongs to
`preceptor:form-analyst`, not the hook.
