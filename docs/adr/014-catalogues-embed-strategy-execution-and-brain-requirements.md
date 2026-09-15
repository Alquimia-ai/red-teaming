# ADR-014: Catalogues embed strategy execution and brain requirements

**Status:** Accepted
**Date:** 2026-09-15
**Tags:** catalogue, contracts, brain, engine, store

## Context

Catalogue behavior was split across a probe-library document and three sidecars. Grounding was
inferred partly from prompt text, while delivery was joined later by strategy id. That made a
strategy incomplete on its own and allowed its prompt, grounding rule and conversation mode to
change under different digests. Runs also treated the presence of a brain as a catalogue-wide mode,
which excluded independent strategies whenever a brain was supplied.

## Decision Drivers

- Make one immutable digest describe everything a strategy will execute.
- Pull a brain and expose registry credentials only when an effective strategy needs it.
- Support fixed and adaptive multi-turn conversations through the governed target door.
- Resolve localized prompts exactly in the language declared by the run.
- Keep executable extension points in code and engagement behavior in the object store.

## Considered Options

### Option A: Extend the existing sidecars — Rejected

**Pros:** Smaller schema change and continued support for old publishers.

**Cons:** Strategy behavior remains distributed across independently addressed objects and joined
by convention.

### Option B: Store one complete catalogue document — Chosen

**Pros:** One digest covers the contract, plugins, brain requirements, prompts and interaction
modes. Publication and run gating can validate the complete behavior before execution.

**Cons:** Schema version 2 and the `brain` run field are breaking changes; unfinished older runs
cannot resume.

## Decision

Publish a catalogue as one canonical schema-version-2 JSON object at
`catalogues/<name>/vNNNNN.json`. It embeds the behavioral contract, plugins and strategies. Every
strategy declares `requires_brain` and one discriminated interaction: `single_turn`,
`scripted_multi_turn` or `adaptive_multi_turn`. Localized fields resolve only by an exact BCP-47
tag. Brain-required interactions carry `{premise}`; independent interactions do not.

`RunSpec.brain` is the sole brain reference and must contain registry, repository and a SHA-256
digest. A run without a brain is rejected when any effective selected strategy requires one. A run
with a brain executes both kinds, but the runner pulls once and gives the brain only to the required
subset. It does not resolve registry credentials or construct a registry client when none of the
selected strategies needs the brain.

Transforms remain code-loaded through descriptors that declare their requirements. Catalogue
documents name transform and attacker keys but contain no code path, model id or credential.
Attacker models are built only for selected adaptive strategies. Fixed scripts and adaptive turns
pass through the same target budget, pacing, retry and trace recording as single-turn probes.

## Consequences

### Positive

- Publication identity covers the whole executable strategy declaration.
- Mixed catalogues run correctly with a brain without discarding independent strategies.
- Every target turn is charged and one work unit still produces one complete trace.
- Production installations start with no implicit business catalogue.

### Negative / Trade-offs

- Frozen specs containing `kb_ref` or catalogue documents without `schema_version: 2` are refused.
- Authors must declare brain use and interaction mode for every strategy.
- A localized catalogue requires the run language to match a declared tag exactly.

## Implementation Notes

The API and CLI accept one YAML or JSON authoring document; the store always writes canonical JSON.
Local compose may publish minimal fixtures. The Helm chart carries no catalogue and runs no seed
hook. Probe identity includes the resolved interaction payload, transform, language and brain-use
declaration, so changing a script or mode produces new work identities.

## Related ADRs

Supersedes [ADR-005](./005-catalogue-bundles-name-constructions-the-runtime-builds.md).

Supersedes [ADR-006](./006-strategies-say-what-deliveries-say-how.md).

Builds on [ADR-003](./003-append-only-store-and-content-identity.md).

Complements [ADR-004](./004-models-are-configuration-and-one-governed-door-to-the-target.md).
