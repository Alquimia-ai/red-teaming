# The store

The one stateful component: an S3-compatible object store, append-only. Every key under a run's
prefix is written once, at the moment the thing it records can no longer change. There is no
`delete` anywhere in the codebase, and no cache is rewritten in place -- a guard refuses both.

## Why append-only, and why content identity

A trace that can be rewritten stops supporting any claim derived from it. So `put` refuses an
existing key (`If-None-Match: *` on S3; `S3ObjectStore.verify()` proves the bucket honours it before
the process serves anything), and every identity derives from content rather than from the moment
of execution: a probe's id from what built it, an attack's id from the probe and its parameters, a
probe set's digest from the sorted set. Nothing in an identity depends on when it ran -- if it did,
a relaunch would find none of its keys and attack the assistant all over again, silently.

## Layout

```
capabilities/conditional-write               the proof the backend refuses a second write

catalogues/<name>/vNNNNN.json                a catalogue bundle's commit key (plugins, strategies)
catalogues/<name>/vNNNNN.contract.json       its contract: principles, weights, verdict tokens
catalogues/<name>/vNNNNN.grounding.json      which strategies need a knowledge base
catalogues/<name>/vNNNNN.delivery.json       which strategies are conversations, through which attacker
priors/<name>/vNNNNN.json                    a natural-query prior

blobs/<sha256>                               a probe set, by content, shared across runs

runs/<id>/spec.json                          frozen at acceptance
runs/<id>/attempts/<attempt>.json            an attempt announced itself
runs/<id>/probes.json                        -> blobs/<digest>, with the generation report
runs/<id>/traces/<attack_id>/<replica>.jsonl.zst   one closed conversation, every turn
runs/<id>/traces/<attack_id>/<replica>.failed      a unit that failed without remedy, with the record
runs/<id>/profile.json                       the weakness profile (control)
runs/<id>/searched.json                      the search was attempted, and how it went
runs/<id>/exploit.json                       the exploitation report (control)
runs/<id>/sessions/exploit.json              the search's dataset session, kept before the dataset
runs/<id>/dataset.json                       the attack dataset, one session per replica
runs/<id>/conduction.json                    what conduction said about itself
runs/<id>/failures/<attempt>.json            an attempt died, and why
runs/<id>/manifest.json                      the run closed; exists <=> COMPLETE
```

Versioned assets are zero-padded so a listing sorts newest last; sidecars land before the commit
key so a half-written publication is never a complete version; publishing what is already
published writes nothing and answers the existing version.

## Resumption is a set difference

```
plan   = expand(spec, probes)                       every (attack_id, replica)
closed = keys under traces/ ending in .jsonl.zst
failed = keys under traces/ ending in .failed
pending = plan - closed - failed
```

A relaunched runner replays the closed units from their traces into the judge, sends the pending
and the failed ones live, and never asks the assistant a question it already answered. Coverage is
the same difference counted per plugin and strategy. Progress, resumption and coverage cannot
disagree with each other or with the result because all three are derived from the same keys.

## Backends

`memory` for tests and single-process rehearsal; `s3` for everything else -- MinIO on the
appliance, S3 on EKS, Cloud Storage's S3-compatible endpoint on GKE. Selected by
`REDTEAM_STORE_BACKEND`; a backend the settings name and the build does not serve refuses to start.

## Durable recovery

New runs reserve every live target call under `calls/entries/` before transport. Results are
separate immutable entries; a reservation without a result remains consumed. The budget header
binds the ledger to the frozen limit, and a recorded exhaustion is terminal for that run's attack.

`recovery/exploit.json` contains search provenance and sessions atomically, including explicit
empty results. `recovery/conduction.json` contains dataset sessions and conduction provenance.
The ordinary deliverable files are verified projections: resume completes interrupted projections
without target interactions. An existing dataset alone is never sufficient for completion.
An interrupted search without a recoverable checkpoint, or legacy evidence with unknown budget or
missing provenance, fails with `recovery_incomplete` and requires a new run id.
