# ADR-002: A stateless API and one runner process per run

**Status:** Accepted
**Date:** 2026-09-10
**Tags:** api, runner, dispatch, store

## Context

A red-teaming run has three stages with very different shapes. Probe generation reads a knowledge
base and a catalogue and produces a content-addressed set of probes; it calls a generator model
and never touches the assistant under test. Conduction sends those probes to a live assistant,
turn by turn, under a budget, a rate limit and a safe-mode gate; it is the only stage with effects
outside the platform and it can run for hours. Assembly builds the attack dataset, the weakness
profile and the manifest from evidence already written.

The platform has to accept a run quickly, be killable at any point without losing closed work,
resume from what is already recorded, and keep the piece that talks to the assistant apart from
the piece that reads the knowledge base. It also has to be operable on a single-node appliance,
where every stateful component is one more thing to back up and monitor.

## Decision Drivers

- Acceptance is fast and idempotent; execution is long and resumable.
- The knowledge base and the assistant are never reachable from the same code path.
- One stateful component to operate: the object store.
- Coordination and liveness come from the platform that runs the process, not from a second
  store that can disagree with it.
- The evidence written during a run is never rewritten.

## Considered Options

### Option A: One service that accepts and executes runs — Rejected

An HTTP service holding runs in memory and executing them in background tasks.

**Pros:** one image, one process, trivial local setup.

**Cons:** a restart loses in-flight runs; a long conduction occupies the service that should be
answering; the knowledge base client and the assistant client live in one process with nothing
keeping them apart.

### Option B: Three images with a job registry — Rejected

A stateless API, a generation-and-measurement service that launches its own jobs, and a per-run
driver, coordinated through an in-memory registry with heartbeats and expiring claims.

**Pros:** each stage isolated by image; generation reusable across runs through content
addressing; the registry answers "is this job alive".

**Cons:** an extra HTTP hop and a job protocol between the driver and generation; a second
stateful piece (the registry) whose view can drift from what the platform knows about the process
-- a dead job can leave a run reporting a phase that is no longer true; two more deployables to
build, ship and monitor.

### Option C: A stateless API and one runner process per run — Chosen

Two images. The API validates a request against the published assets and the connector's declared
capabilities, freezes the request as an immutable spec in the object store, launches one runner
and answers `202`. The runner performs generation in-process (or reuses an existing probe set),
conducts the plan against the assistant, assembles the dataset, profile and manifest, and
notifies a webhook. Generation and conduction are separate packages that may not import each
other; the runner is the only place where both are composed. Coordination is the platform's: a
Kubernetes Job, a Docker container or a local subprocess with a unique name per run. Liveness is
read from the same platform through the dispatcher; progress is derived from the keys already
written under the run's prefix.

**Pros:** two deployables; one stateful component; no protocol between stages; the invariant
"generation never reaches the assistant, conduction never reads the knowledge base" is enforced
by an import guard that CI runs; status can never disagree with the platform.

**Cons:** the runner image carries every dependency; the API carries the catalogue validation
library so publication can fail fast; "is the runner alive" requires the API to read the
platform, not only to launch on it.

## Decision

Adopt Option C. The API is stateless and derives everything it reports from the object store and
the dispatcher. The runner is one process per run, launched through a dispatcher whose backends
are the platform itself, and is the only component that reaches the assistant under test. There
is no job registry and no progress cache: the object store is append-only without exception.

## Consequences

### Positive

- Killing any component loses at most the conversations in flight; resumption is the difference
  between the frozen plan and the keys that exist.
- A second launch of the same run is refused by the platform's own uniqueness of names.
- The appliance operates one stateful service besides the assistant it evaluates.
- Package-level isolation is testable without building an image.

### Negative / Trade-offs

- The dispatcher needs a `status` operation per backend; the API needs read access to the
  platform where it launches.
- A stalled runner is detected by comparing store-derived phase with platform state, and the
  remedy is a resume, not an automatic restart.
- The API image is heavier than a pure gate because it validates catalogues semantically.

## Implementation Notes

- Dispatcher backends: `local_subprocess` (pid and lock file), `docker` (container named after
  the run), `k8s_job` (a `batch/v1` Job named after the run; a name conflict is
  `AlreadyRunning`). Each implements `launch` and `status`.
- Run phases derive from store keys: `spec.json` → accepted; an attempt marker → generating;
  `probes.json` and traces → attacking; `manifest.json` → complete; a failure record on the
  latest attempt → failed. The API reports the dispatcher's state alongside the phase.
- The import guard forbids `probes → target` and `engine → knowledge, probes`; the API's
  dependency closure carries neither the target nor the knowledge client.
