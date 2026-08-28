---
bundle:
  name: preceptor
  version: 0.1.0
  description: |
    Observe agent form, correct from evidence, and remove corrections that stop
    earning their place. A standing feedback loop for context engineering.

includes:
  - bundle: git+https://github.com/microsoft/amplifier-foundation@main
  - bundle: preceptor:behaviors/preceptor
---

# Preceptor

Instructions given to a model are not permanent. They are hypotheses with a cost.

Preceptor observes. It does not gate, block, or override.

<!-- The cue contract, the [cue:id] convention, and the removal rule live in
     context/cue-awareness.md, which loads alongside this. Do not restate them
     here — this body is emitted ahead of every context file, so anything
     duplicated between the two is paid for twice on every turn. -->

---

@foundation:context/shared/common-system-base.md
