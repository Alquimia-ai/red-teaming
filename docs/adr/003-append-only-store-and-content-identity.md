# ADR-003: Append-only store and content-derived identity

**Status:** Accepted
**Date:** 2026-09-10
**Tags:** store, contracts, evidence

## Context

A run produces evidence about somebody else's assistant: the conversations it conducted, the
dataset built from them, the plan it executed and the request that was frozen at acceptance. That
evidence has to be auditable months later, and it has to survive the process that produced it
dying at any point -- a runner is killed, a node restarts, a budget runs out. It also has to
support resumption: a relaunched runner must do the work that never closed and none of the work
that did, or the assistant is attacked twice.

The platform has one stateful component, an S3-compatible object store, and no database. Whatever
guarantees the evidence needs have to come from how keys are named and how writes are performed.

## Decision Drivers

- A trace, once written, is never different from what was written.
- A relaunched runner reaches the same place as an uninterrupted one, without a progress table.
- Two runs over the same knowledge base and catalogue do not generate the same probes twice.
- Progress and coverage cannot disagree with the result.
- One process per run is refused, loudly, when it slips.

## Considered Options

### Option A: Overwritable keys and a progress record — Rejected

Keys are written freely; a `progress.json` records which units closed and is rewritten as work
advances; a database or the same file records phase.

**Pros:** cheap status reads; familiar.

**Cons:** the progress record can lag, double-count or be lost, and it can disagree with the traces
that exist; a rewritten trace is a claim nobody has to believe; a second runner overwrites the
first's work silently.

### Option B: Append-only keys, identities derived from content, status derived from keys — Chosen

Every key under a run's prefix is written once, when the thing it records can no longer change,
with a conditional create the store decides atomically. A work unit's key is derived from the plan
-- the probe's identity and the attack's parameters, never a timestamp or a random value -- so the
key is known before the unit executes and "the key exists" and "the unit closed" are one
statement. Probe sets are content-addressed and shared across runs; the run keeps a pointer.
Progress, resumption and coverage are the same set difference between the plan and a listing.
The interface has no `delete`.

**Pros:** evidence is evidence; resumption is a listing; coverage cannot drift; a second writer of
one key is refused by the store itself; the only stateful component needs no coordination.

**Cons:** a status read lists a prefix rather than reading a row; read-after-write consistency is
an explicit assumption to verify on any self-hosted store; nothing can be corrected in place --
a wrong artifact is superseded by a new run.

## Decision

Adopt Option B. The store is append-only without exception: `put` is a conditional create, every
backend proves it refuses a second write before serving, and there is no `delete`. Identities are
derived from content -- `attack_id` from the probe and its parameters, the probe set's digest from
the sorted set -- and never from the moment of execution. Phase, progress and coverage are derived
from the keys that exist, sliced by plugin and strategy; no cache is written to make that faster.

## Consequences

### Positive

- A killed runner loses only the conversations in flight; the next attempt resumes from the
  difference and never repeats a closed conversation.
- The manifest's coverage and the status endpoint's progress come from the same keys and cannot
  disagree.
- Two publishers of one asset version collide instead of overwriting; two runners of one run
  collide on their first trace.
- Probe generation is deduplicated across runs by digest.

### Negative / Trade-offs

- Status reads list a prefix; for runs of thousands of units that is measurably slower than a row
  read, and accepted.
- A backend that does not honour `If-None-Match: *` cannot serve; that is checked at startup and
  refused rather than degraded.
- Retention is a policy question that has to exist from the first day: traces contain the
  assistant's real answers and nothing in the platform removes them.

## Implementation Notes

- `redteam_store.interface.ObjectStore`: `put`, `get`, `exists`, `list_prefix`; no `delete`.
  `S3ObjectStore.verify()` writes a probe key twice and demands a `PreconditionFailed`.
- `redteam_store.layout`: the only module that spells a key. Deterministic paths under
  `runs/{run_id}/`, content-addressed `blobs/{digest}`, versioned assets under
  `catalogues/{name}/v{00001}.json` with sidecars beside them.
- `redteam_contracts.plan.attack_id` hashes the canonical JSON of `probe_id` and `attack_params`;
  `tests/test_plan_determinism.py` pins the result across processes.
- `redteam_store.resume.difference` is resumption, progress and coverage.
- `tests/guards/test_no_delete.py` keeps the interface without a `delete`.
