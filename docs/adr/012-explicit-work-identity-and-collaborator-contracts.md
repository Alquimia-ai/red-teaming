# ADR-012: Explicit work identity and collaborator contracts

**Status:** Accepted
**Date:** 2026-09-14
**Tags:** engine, typing, architecture

## Context

Recording, delivery selection, replay and dataset assembly shared a positional assumption about
Gaussia's profiler. Known collaborators were often annotated as Any, hiding their requirements.

## Decision Drivers

- Preserve replica identity and immutable evidence during recovery.
- Detect invalid collaborators without changing the package dependency graph.
- Keep the external profiler's sequential requirement local.

## Considered Options

### Option A: Retain coordinated positional counters — Rejected

**Pros:** Minimal code changes.

**Cons:** A filter or reordered result can assign evidence to a different unit.

### Option B: Carry unit identity behind one profiling adapter — Chosen

**Pros:** Recording and assembly consume explicit identities; replay bypasses live governance.

**Cons:** The adapter still depends on Gaussia sending one query per probe in order.

## Decision

PlanProfiler owns the sequential exchange cursor and validates the returned outcome association.
Every graded outcome carries its WorkUnit and Probe; recording receives the WorkUnit explicitly.
Use existing domain types and small structural contracts for internal dependencies, keeping
configuration and credential composition in the runner.

## Consequences

### Positive

- Replica outcomes remain distinct even when assembled in another order.
- Closed traces replay without new target calls; failed markers remain eligible for execution.
- Type checks reject collaborators that do not provide the required interface.

### Negative / Trade-offs

- Identical queries and probe ids cannot reveal an upstream permutation of identical replicas;
  the real profiler's sequential behavior remains an explicitly tested integration contract.
- Gaussia's package lacks a typing marker, so its domain annotations do not replace behavioral
  integration tests or local collaborator protocols.

## Implementation Notes

Generated exploitation exchanges continue using the existing content-derived keys and never count
as planned coverage. On-disk identities, traces, checkpoints and datasets are unchanged. Missing,
extra or mismatched profiler results cannot produce identified outcomes or a completed dataset.
