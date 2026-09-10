# ADR-005: Catalogue bundles name constructions the runtime builds

**Status:** Accepted
**Date:** 2026-09-10
**Tags:** catalogue, probes, contracts

## Context

A catalogue is the engagement's risk taxonomy: which families of failure to test, how each probe is
built from the knowledge base, what the assistant is held to, which strategies need a base and how
each probe reaches the assistant. gaussia supplies the plugin/strategy pattern, a probe library and
four premise constructions, and says plainly that it ships no catalogue: a risk taxonomy *is* what
the evaluation measures, so a shipped one would become a cross-user standard nobody chose.

Three of gaussia's four constructions misfire outside the corpus they were written for: a `-2`
suffix reads as a typo rather than as a sibling product, a digit increment mangles a figure written
with thousands separators and leaves an entity with no digits unchanged -- which the engine then
labels documented, quietly turning an attack strategy into a second control -- and an English `not`
prepended to a Spanish fact is not a falsehood anybody would state. The catalogue also has no place
to say what the assistant is held to, which strategies need a base, or that a strategy is a
conversation rather than one turn: `StrategySpec` drops an unknown key silently.

## Decision Drivers

- The catalogue stays data: no code, no model ids, nothing that ships on our cadence.
- A strategy that declares it attacks must attack; a construction that finds nothing to deform must
  say so rather than come back unchanged.
- Premises read like the client's own vocabulary, in the client's language, never ours.
- A bundle validates and publishes without a brain and without a model provider.
- The contract the plugins charge cannot drift from the catalogue that charges it.

## Considered Options

### Option A: Code paths in the catalogue — Rejected

A strategy names a Python class path for its construction; the runtime imports it.

**Pros:** unlimited constructions without touching the platform.

**Cons:** the catalogue becomes code with a version of its own; a published asset can name a class
that no longer exists; a construction's context -- the boundary, the language, the generator --
has nowhere to come from but global state.

### Option B: Word lists and per-domain rules baked into the platform — Rejected

Ship a vocabulary of plausible qualifiers per language and a set of domain rules.

**Pros:** works out of the box for the domains anticipated.

**Cons:** a vocabulary of ours standing in for the client's is the same mistake as an invented
realism pool: it measures our imagination. Every unanticipated domain is wrong by default.

### Option C: Keys resolved by a registry, closed over the run's context — Chosen

A strategy names a construction by **key**. A registry in the catalogue package binds each key to a
builder; the builder receives `Ingredients` -- the boundary the corpus attests for that entity kind,
the run's declared context, the generator model when declared -- and returns a configured
construction. Deterministic constructions (`swap_token`, `shift_figure`, `shift_date`) read their
rule off the datum's own shape and need no model; the model-driven one (`contextual_sibling`)
requires the run's context and generator and is refused by name when either is absent. Every
construction resolves its whole mapping before the first probe and reports what it could not
deform, so a strategy that produced only documented premises is surfaced as *degenerate* rather
than counted as an attack. Keys are added, never replaced; a key colliding with gaussia's four is
refused.

What the catalogue cannot say inside `catalogue.json` travels as sidecars of the same versioned
bundle: `contract.json` (required -- the principles the plugins charge, with severities summing to
one and rubrics handed to the judge unmodified), `grounding.json` (strategies needing a base beyond
what their `{premise}` slot already says) and `delivery.json` (conversations an attacker steers, by
attacker id and never by model). Publishing validates the bundle as a whole -- gaussia's six semantic
rejections against the bundle's own contract, the grounding against the phrasings, the delivery
against the strategies -- writes the sidecars before the catalogue's commit key, and answers an
identical re-publish with the existing version.

**Pros:** the catalogue stays data and the code stays ours; premises are the corpus' own
vocabulary; nothing silently becomes a control; a bundle publishes with no brain and no model; the
contract and the catalogue are one version.

**Cons:** a new construction is a change to the catalogue package; a model-driven construction
costs a request per entity kind and a run that wants it must declare a generator.

## Decision

Adopt Option C. Catalogue bundles are data that name constructions by key; the catalogue package
builds them with the run's boundary, context and generator, reports what could not be built, and
validates and publishes the bundle -- catalogue, contract, grounding, delivery -- as one version.
Probe identity derives from the engine, the strategy, the premise and how it was derived, never from
a position in the boundary.

## Consequences

### Positive

- Every probe is citable to the block its premise came from, and its `doc` label is derived from
  the base and confirmed by an independent check, never copied from the strategy.
- A degenerate strategy and every entity nothing could deform appear in the generation report.
- Adding an entity to the brain changes no existing probe's identity, so resumption holds.
- The API can validate and publish a bundle synchronously with the same code the runner generates
  from.

### Negative / Trade-offs

- The catalogue package carries gaussia, and so does the API image.
- Kinds a base does not carry are only detectable by a run that has the base; publication accepts
  the kinds as named.
- The near-miss check is calibrated on short names; sentence-shaped kinds opt out of it.

## Implementation Notes

- `redteam_catalogue.premises`: `register`, `build_transforms`, `unresolved`, `DeclaredKey`,
  `ContextRequired`; `transforms`: `SwapAttestedToken`, `ShiftFigure`, `ShiftDate`; `contextual`:
  `ContextualSiblingTransform`.
- `redteam_catalogue.assets.publish`: sidecars first, contract required, identical re-publish
  answered as the existing version; `generatable` and `narrow` decide what a run generates.
- `redteam_catalogue.bundle.load_bundle`: the on-disk shape the CLI publishes.
- `redteam_probes.generate`: content-derived probe identity, `DegenerateStrategy`, `digest_of`;
  `generate_run.generate_for`: one pull per run, blob written once, `probes.json` pins the set.
- Seeds: `deploy/seed/catalogues/assistant-baseline` and `assistant-invented-siblings`; skill
  `/catalogue`.
