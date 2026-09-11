# ADR-009: Durable call reservations and atomic stage recovery

**Status:** Accepted
**Date:** 2026-09-11
**Tags:** engine, store, runner

## Context

Run retries previously renewed target-call allowance and could skip sessions or provenance after an interrupted pair of writes.

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

Reserve every target call with an append-only conditional write before transport, counting unknown outcomes as consumed. Commit each search and conduction result as one recovery record before projecting deliverables; only verified projections can close a run.

## Consequences

### Positive

- Transport retries and conversation turns respect a run-wide limit; recoverable results retain their provenance without repeating target calls.

### Negative / Trade-offs

- A crash after reservation but before sending consumes allowance. Legacy attempts without trustworthy budget or provenance cannot resume; a new run id is required.

## Implementation Notes

Call results are recorded separately from reservations to retain partial evidence. Replayed responses bypass charging. A durable exhaustion marker prevents later completion over truncated evidence. Search-start records without a checkpoint block automatic search repetition. Existing completed manifests remain readable. Stop older runners before using this format; older code must never write new-format runs. The wall-clock budget is unchanged.
