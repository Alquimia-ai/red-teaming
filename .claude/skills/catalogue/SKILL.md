---
name: catalogue
description: Author or revise a catalogue bundle (catalogue.json, contract.json, grounding.json, delivery.json) for a red-teaming run, then validate and publish it. Use when setting up an engagement's risk taxonomy or when publishing refuses a bundle.
allowed-tools: Bash, Read, Write, Edit, Grep, Glob
---

# Author a catalogue bundle

A bundle is a directory with four files, published as **one** version:

| File | Required | What it declares |
|---|---|---|
| `catalogue.json` | yes | `plugins` (risk families, each charging one `principle`) and `strategies` (how a probe is built) |
| `contract.json` (or `.yaml`) | yes | The principles the assistant is held to: `id`, `weight` (a severity; they sum to 1.0), `rubric`; plus `verdict.positive`/`negative` tokens |
| `grounding.json` | when needed | `{"needs_base": [strategy ids]}` — strategies that need a knowledge base beyond what their phrasing says |
| `delivery.json` | when needed | `{"delivery": {strategy id: {"turns": "many", "attacker": id, "max_turns": n}}}` — conversations an attacker steers |

Seeds to start from: `deploy/seed/catalogues/assistant-baseline/` and `assistant-invented-siblings/`.

## When to use this skill

- Setting up an engagement: which failures to test, how to phrase them, what the assistant is held to.
- `redteam catalogue validate` or `publish` refused a bundle and the message names a plugin, strategy, construction or sidecar.

Do **not** use it to bind models: a catalogue names attackers by **id** and never a model; the run
binds ids to models in `RunSpec.attackers`.

## Steps

1. **Write the contract first.** Each principle is one rule, stated in the positive, with the
   boundary named and the question explicit — it is handed to the judge unmodified. Weights are
   severities, not confidences; they must sum to `1.0`. Verdict tokens are spelled as tokens
   (`"YES"`, `" YES"`), quoted in YAML so they never parse as booleans.
2. **Plugins are risk families, not principles.** `id` names *what goes wrong* (`invented-entity`,
   `configuration-disclosure`); `principle` must be an id from the contract. Several plugins may
   charge one principle; one plugin charges exactly one. `description` is documentation and reaches
   the attacker as the conversation's objective, so write it as what the attack is after.
3. **Strategies are how a probe is built.**
   - `entity_kind`: what the strategy asks about (`product`, `fact`, `assistant`, …). A grounded run
     enumerates every entity of that kind from the knowledge base; a kind the base does not carry is
     refused by name at generation.
   - `transform` (the construction), one of: gaussia's four (`keep_real`, `mutate_to_fake`,
     `flip_value`, `flip_fact`), the deterministic three — `swap_token` (recombine tokens the corpus
     attests, for name-shaped kinds), `shift_figure` (move a figure ×1.15 in the corpus' own
     notation), `shift_date` (move a date two months, day clamped) — or the model-driven
     `contextual_sibling` (invent a plausible sibling with the run's `generator` and `context`;
     refused by name when the run declares neither).
   - `doc`: `0` when the premise is invented, `1` when it is documented. The label is derived from
     the base at generation, never copied from here; a `doc: 0` strategy that only produces
     documented premises is reported as *degenerate*.
   - `phrasing_hint`: the query. `{premise}` marks where the entity goes; a phrasing carrying the
     slot **needs a base** and runs only in grounded runs; a phrasing without it runs only in
     black-box runs. One catalogue may carry both halves.
   - `description`: comma-separated clauses become the probe's attributes and are the only thing
     about the strategy the exploiter's search can ground a category in.
   - A **control** is a strategy with `"plugin": null`: sent, graded, excluded from every rate. Keep
     at least one per entity kind you attack.
4. **Declare grounding.** Every strategy whose phrasing carries `{premise}` must be listed in
   `needs_base` (publishing refuses otherwise); a slotless strategy may also be listed when it wants
   the premise appended.
5. **Declare delivery** for strategies that should be conversations: `"turns": "many"`, an
   `attacker` id, `max_turns` ≥ 2 (default 6). A control cannot be conducted. Unknown keys — `model`
   included — are refused.
6. **Validate, then publish:**

   ```bash
   redteam catalogue validate <dir>
   redteam catalogue publish <name> <dir>
   ```

   Identical content re-publishes as the existing version; any change opens a new one. Several
   catalogues in one run must carry the same contract (same digest).

## Refusals and what they mean

| Message | Fix |
|---|---|
| plugins name principles the contract does not carry | add the principle to `contract.json` or fix the plugin's `principle` |
| weights … have to sum to 1.0 | adjust the severities |
| transforms outside … | the `transform` key is not registered; use one of the keys above |
| lean on a premise and are not declared as needing a knowledge base | add them to `grounding.json` |
| delivery … names strategies the catalogue does not carry / conducts … controls | fix the ids; controls are never conducted |
| carries keys this sidecar does not know | remove the key (a model never travels in a catalogue) |
| needs the run's context / generator model | the run must declare `context` and `generator` for `contextual_sibling` |

## Output

Report the bundle directory, the published name and version, the contract digest, and which
strategies are conducted as conversations (and the attacker ids the run will have to bind).
