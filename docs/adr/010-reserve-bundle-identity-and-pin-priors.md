# ADR-010: Reserve bundle identity and pin realism priors

**Status:** Accepted
**Date:** 2026-09-11
**Tags:** catalogue, store, contracts, api

## Context

Concurrent catalogue writers could mix sidecars, while accepted runs selected a realism prior by its mutable latest version.

## Decision Drivers

- Preserve immutable evidence across interruption and concurrency.
- Keep resumption deterministic and make incomplete recovery explicit.

## Considered Options

### Option A: Infer completion from individual files — Rejected

**Pros:** Fewer persisted records and minimal changes.

**Cons:** An interrupted write or concurrent request can change the meaning of existing evidence.

### Option B: Commit explicit recovery identity before proceeding — Chosen

**Pros:** Recovery has a durable source of truth and conflicts are observable.

**Cons:** Additional records and conservative handling of unknown legacy state.

## Decision

Reserve each catalogue version with a canonical identity of the catalogue and every sidecar, including absence, before writing sidecars. Resolve the realism prior version and digest at acceptance and verify them at execution.

## Consequences

### Positive

- Identical interrupted publications can finish safely; different bundles cannot share a reservation. Later publications cannot change an accepted run.

### Negative / Trade-offs

- Unclaimed legacy fragments are skipped. Legacy runs that need an unpinned prior cannot safely resume. New and old catalogue publishers must not overlap.

## Implementation Notes

The catalogue commit key remains unchanged and is written last after sidecar verification. Claims are immutable and are not catalogue versions. Optional request pins become required frozen identities when a prior is declared. Existing completed runs and published catalogues stay readable; no store keys are rewritten.
