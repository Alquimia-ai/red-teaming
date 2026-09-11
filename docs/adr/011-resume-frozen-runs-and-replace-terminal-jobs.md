# ADR-011: Resume frozen runs and replace terminal Jobs

**Status:** Accepted
**Date:** 2026-09-11
**Tags:** api, dispatch, deploy

## Context

An identical retry was validated against newly published catalogues, and terminal Kubernetes Jobs held a run name until TTL expiry.

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

Resolve retries from their frozen specification before consulting current assets. Retain one Kubernetes Job name per run; reclaim only a managed terminal Job whose Pods have terminated, with UID and resourceVersion preconditions and foreground deletion.

## Consequences

### Positive

- An accepted request remains repeatable and terminal Jobs do not block recovery until TTL. Concurrent resumers cannot remove each other's replacement or create two active Jobs.

### Negative / Trade-offs

- Deletion can outlive the bounded wait and return a retryable dispatch error. Terminal Job logs expire when the Job is reclaimed; durable run evidence stays in the object store.

## Implementation Notes

API creation re-reads the winning specification after conditional-write conflicts or validation races. Explicit conflicting pins return 409. Completed runs are not relaunched. Pod listings use the existing run-id label, covering older Kubernetes versions. Kubernetes DELETE is the sole infrastructure exception to the no-delete guard; ObjectStore remains append-only. Namespace RBAC already grants jobs/delete and pods/list.
