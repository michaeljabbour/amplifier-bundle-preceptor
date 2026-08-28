# The arms

The A/B lever in `amplifier-bundle-evaluation` is `agents/<id>/install.yaml`. Two agent
directories differing **only** in their `amplifier bundle add` line are two arms of a
controlled experiment. Everything else — task, model, DTU profile, timeout — is held fixed.

Copy these into an `agents/` dir alongside a `tasks/` dir, then:

```bash
amplifier-evaluation run \
  --agents-dir bench/arms --tasks-dir <tasks> \
  --agent baseline --agent preceptor-on --agent sham \
  --trials-per-pair 10 --max-parallel 2 \
  --output-dir bench-results --run-id ablation-001
```

## Why these six

| Arm | Instruction layer | The question it answers |
|---|---|---|
| `baseline` | foundation only | control |
| `preceptor-off` | + preceptor, cues disabled | what does *loading* cost? |
| `preceptor-on` | + preceptor, earned cues dosed | **the claim** |
| `sham` | + cues earned on a *different* model/domain, matched count and length | is "earned" real, or is any plausible text this good? |
| `frozen` | + a one-time human profile, never updated | is *continuous* worth anything over a batch pass? |
| `bloat` | + N plausible unearned instructions | **does removal help at all?** |

`sham` and `frozen` are the arms that can embarrass this project, which is exactly why
they are not optional. If `preceptor-on ≈ sham`, then "earned" and "per-model" mean nothing
and this is an expensive generic prompt. If `preceptor-on ≈ frozen`, the continuous loop is
unjustified and the honest product is a scheduled batch pass, not a runtime.

`bloat` exists because of **arXiv:2601.20404**, which found that *adding* an AGENTS.md file
made agents **28.64% faster** with 16.58% fewer output tokens. That is the only
peer-reviewed instruction-ablation result in the literature and it points against this
bundle's thesis. `bloat` tests the thesis in the direction it might fail.

## Power

`bench/verdict.py:required_n()` on the existing overhead data:

| Effect to detect | n per arm |
|---|---|
| d = 0.8 (large) | **25** |
| d = 0.5 (medium) | **63** |

At 2-way concurrency and multi-minute trials, 63 × 6 arms is not a weekend. Start with the
three arms that carry the argument — `baseline`, `preceptor-on`, `sham` — at n=25, and only
add the rest if the first cut shows anything.

## Keys

Do **not** bake `ANTHROPIC_API_KEY` into a published golden image. `passthrough.services`
writes it in plaintext to `/etc/profile.d/dtu-env.sh` inside the container, and
`incus publish` would capture it. Provision the golden image without keys and inject
per-trial.
