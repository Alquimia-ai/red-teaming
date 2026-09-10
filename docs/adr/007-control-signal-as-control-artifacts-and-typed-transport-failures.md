# ADR-007: Control signal persists as control artifacts and transport failures never close a unit

**Status:** Accepted
**Date:** 2026-09-10
**Tags:** engine, store, contracts, evidence

## Context

A run grades every exchange inside itself to steer: the Profiler's grades build the weakness
profile the Exploiter searches from, and the Exploiter's grades rank the categories it found. These
grades come from the control judge with thresholds -- `tau`, `eta` -- that are the operator's
judgement about their own domain. They are how the run decides what to press on, and an operator
wants to read them: which principles broke most, which categories broke the assistant
reproducibly. At the same time the run's coverage -- what was planned, what closed, what failed --
is read off the store's keys and must not depend on any grade.

Separately, an exchange can fail at the transport level: a rate limit, a refused credential, a
gateway that was down, an answer that could not be read. Graded, such a failure reads as compliance
and an outage becomes a clean bill of health; written under the unit's key, it closes a unit the
assistant never answered and the only way to retry it is a new run id.

## Decision Drivers

- The profile and the report are delivered to the operator and are never part of the coverage.
- Generation and judgement stay independent: the generator that writes probes never grades them.
- A failed exchange is evidence of the channel, not of the assistant.
- The record of a failure says what kind it was and what the target said, not which Python class
  raised.
- What to do about a failure is a policy of the engine, read off the kind, in one table.

## Considered Options

### Option A: Discard the profile and the report at the end of conduction — Rejected

Only the dataset and the traces leave the run; the control grades die with the process.

**Pros:** nothing with a threshold in it can be mistaken for a measurement.

**Cons:** the operator loses the two artifacts that say what the run learned and how it searched;
a relaunch that finds the dataset cannot say which weaknesses seeded the search.

### Option B: Fold control grades into the manifest as scores — Rejected

The manifest carries the profile's rates and the report's ranking beside the coverage.

**Pros:** one file to read.

**Cons:** a rate beside a denominator invites a division the run never measured; a threshold in the
manifest is a threshold in the deliverable.

### Option C: Control artifacts under their own keys, named by the manifest, outside the coverage — Chosen

The weakness profile is written to `profile.json` the moment profiling closes and passes the
thin-profile check, before the search starts; the exploitation report is written to `exploit.json`
the moment the search returns; a marker records that the search was attempted and how it went, so a
relaunch never searches twice. The manifest names both keys as control artifacts and carries their
provenance in `components`; the coverage is `planned`, `closed` and `failed` in total and per plugin
and strategy, derived from the plan against the store's keys alone. Transport failures are typed
records produced by the adapter and read by the engine's policy table -- retry, give up, abort --
by kind; a failed exchange is written under the unit's failure marker with the record as its body,
never as a trace, so the unit reads `failed`, the next attempt sends it live, and the evidence of
what went wrong stays in the store. When one kind explains an outage, the attempt dies as that kind
with the target's own words in the failure record.

**Pros:** the operator reads what the run learned; the coverage cannot be moved by a grade; a
relaunch resumes without repeating the search; an outage is diagnosed from the failure record
without opening a trace.

**Cons:** two more keys per run; a profile of an outage is never written, so a run refused as too
thin leaves no profile; the policy table has to be kept in step with the kinds the adapter produces.

## Decision

Adopt Option C. The profile and the report persist as control artifacts named by the manifest and
excluded from the coverage; the control judge is never the generator; a transport failure is a typed
record that marks its unit failed and is acted on by kind, and it never closes a unit.

## Consequences

### Positive

- `profile.json` and `exploit.json` are readable deliverables with the provenance to interpret
  them, and `components` says why a run did not exploit.
- Coverage is the same difference resumption reads; no grade can move it.
- A failure record names the kind -- `unauthorized`, `rate_limited` -- and what the target said.
- A run that hit its budget or lost its channel is not a lost run: everything closed is in the
  store with honest coverage.

### Negative / Trade-offs

- A reader of `profile.json` sees rates computed with thresholds and has to know they are control.
- The thin-profile refusal is generic when failures are mixed; only a dominant kind is typed.
- Retries are real calls: a run that retries a rate limit pays for the retry in its budget.

## Implementation Notes

- `redteam_engine.artifacts.ControlArtifacts`: `profile(result)`, `exploit(report)`, append-only.
- `redteam_engine.conduct.conduct`: the thin-profile check before the profile is kept; `Conducted`
  carries counts, keys and components and never the report.
- `redteam_store.layout`: `profile`, `exploit`, `searched`, `trace_failure`.
- `redteam_engine.failure_policy`: `Action.RETRY | GIVE_UP | ABORT` by kind;
  `redteam_engine.errors`: one exception per kind, `error_for`; `redteam_engine.ledger`: the
  attempt's failures and the typed verdict.
- `redteam_engine.recording.Recorder`: a failed final answer marks the unit; a conducted
  conversation whose last turn failed is in the same position.
- `redteam_contracts.manifest.Manifest`: `profile`, `exploit`, `coverage`; `FailureRecord.kind`
  and `.failure`.

## Related ADRs

- Builds on [ADR-003](./003-append-only-store-and-content-identity.md)
- Complements [ADR-006](./006-strategies-say-what-deliveries-say-how.md)
