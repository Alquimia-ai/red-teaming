# Running the catalogue

## Publish

```bash
redteam catalogue validate catalogues/owasp-agent-security.json
redteam catalogue publish catalogues/owasp-agent-security.json
```

Validated in process against `check_document` before this was committed.

## What a run needs

- **Black box.** Every strategy has `requires_brain: false` and no `{premise}` slot, so none
  needs a knowledge base.
- **An attacker bound to `crescendo`.** 17 attacks are `adaptive_multi_turn`: they send their
  opening and an attacker model steers the rest, up to 4 turns. The run binds the id to a model in
  `RunSpec.attackers`.
- **The same contract as any catalogue run alongside it.** A run over several catalogues requires
  identical contracts. This one does not match `deploy/seed/catalogues/assistant-baseline.json`,
  so the two cannot run together as they stand.

## Three things the platform does that shape the results

- **The attacker only sees the plugin's `description`.** It is the conversation's objective, and
  nothing about the strategy crosses to it. Multi-turn attacks under one plugin therefore differ
  only in their opening turn. Plugin descriptions are instructions to the attacker, not
  documentation.
- **The judge grades the final answer.** Every turn is recorded, but an agent that gave way at
  turn two and recovered at turn four reads as clean. The rubrics are written for a final answer.
- **Controls cannot be conducted.** The 5 multi-turn controls are fixed scripts
  (`scripted_multi_turn`); an attacker steers attacks only.

## Open

- **The canary is fixed.** `COMPROMISED` is public in this repository, so an agent could filter
  it. A random token per run needs support at generation time.
- **Weights are equal** (0.125 each). Severity is the contract owner's call.
