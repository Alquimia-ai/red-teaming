# The catalogue bundle

A catalogue is the engagement's risk taxonomy, and it is **data**: it ships on the engagement's
cadence, not the platform's, and it names no model and no code path. A bundle is a directory of
up to four files, published as one version.

| File | Declares | Required |
|---|---|---|
| `catalogue.json` | plugins (a risk family, and the contract principle it charges) and strategies (how a probe is built: entity kind, construction, `doc`, phrasing) | yes |
| `contract.json` (or `.yaml`) | the behavioural contract: principles with an id, a severity weight (summing to one) and a rubric handed to the judge unmodified; the verdict tokens | yes |
| `grounding.json` | `needs_base`: strategies that need a knowledge base beyond what their phrasing says | no |
| `delivery.json` | `delivery`: strategies delivered as a conversation (`turns: many`), through which attacker **id**, bounded by `max_turns` | no |

Publishing validates the whole bundle against its own contract -- gaussia's six semantic
rejections plus the grounding against the phrasings and the delivery against the strategies -- and
refuses anything else; `POST /catalogues:validate` runs the same checks and writes nothing.

## Constructions

A strategy names its construction by **key**, and a registry in the catalogue package builds it
for the run. Deterministic constructions read their rule off the datum's own shape and need no
model: `swap_token` recombines tokens the corpus attests, `shift_figure` moves a figure respecting
its notation, `shift_date` moves a date respecting its pattern. The model-driven one,
`contextual_sibling`, invents a plausible sibling of the entity with the run's generator in the
run's declared language, domain and tone; a run naming it without a generator and a context is
refused at the gate. What a construction could not deform is reported, never substituted: a
strategy that produced only documented premises tested nothing, and the report says so.

## Two halves

A strategy whose phrasing carries `{premise}` needs a base to draw one from; one that stands
without a premise must not be handed one. So every run generates the half of each catalogue
written for its shape -- grounded, or brainless -- and the report names what was set aside. A
control (a strategy with no plugin) survives every selector: it is the only thing separating "the
assistant is careful" from "the questions were easy".

## Delivery

The sidecar is a third axis beside the premise and the phrasing. `many` turns means the probe's
query opens a conversation an attacker steers toward the plugin's objective -- the plugin's own
description and principle, never words of ours -- for at most `max_turns` agent turns. The
catalogue names the attacker by id; the run binds the id to a model in `RunSpec.attackers`, with
its own credential reference and its own line in the manifest. The whole conversation is one
exchange to the judge and one trace in the store.

## One contract per run

A run may name several bundles; they have to carry the same contract, compared by digest of the
canonical bytes. Two bundles that disagree on a weight or a rubric's wording are refused at the
gate rather than reconciled in silence.

Authoring is documented in the `/catalogue` skill; two bundles ship under `deploy/seed/catalogues/`
as a starting point, and every engagement is expected to publish its own.
