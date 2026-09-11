"""Closing a run, and recording that an attempt died.

Coverage here is not computed, it is *read off* the same difference that decided what to execute.
That is the whole argument for the platform having no database: progress, resumption and coverage
are one difference over one set of keys, so they cannot disagree with each other or with the result.
"""

from __future__ import annotations

import json
import secrets
from datetime import UTC, datetime

from redteam_contracts.manifest import CoverageReport, FailureRecord, Manifest
from redteam_store import layout, manifests
from redteam_store.interface import ObjectStore


def write_manifest(
    store: ObjectStore,
    *,
    run_id: str,
    spec_digest: str,
    probes_digest: str | None,
    dataset: str | None,
    profile: str | None,
    exploit: str | None,
    n_total_traces: int,
    coverage: CoverageReport,
    components: dict[str, str],
) -> Manifest:
    """Write the one file a consumer reads to know whether a run is usable.

    Only a run that closed gets here: the phase is COMPLETE by construction. A failed attempt goes
    through `write_failure`, under a different key, because this key's existence *is* completion to
    everything that reads the store.
    """
    return manifests.write(
        store,
        run_id=run_id,
        spec_digest=spec_digest,
        probes_digest=probes_digest,
        dataset=dataset,
        profile=profile,
        exploit=exploit,
        n_total_traces=n_total_traces,
        coverage=coverage,
        components=components,
    )


def begin_attempt(store: ObjectStore, *, run_id: str) -> str:
    """Say this attempt has begun, under a key of its own, and return the id that names it.

    Written before anything else, so that a failure record can be matched to the attempt that wrote
    it. A record alone says an attempt died and nothing about whether a later one has since begun,
    so the status would read `failed` for the whole life of the relaunch -- and a consumer's poll
    loop, which stops on `failed`, would give up exactly when the retry policy resumed. With the
    marker, `failed` holds only while the newest attempt is the one that left a record.
    """
    attempt = _attempt_id()
    store.put(
        layout.attempt(run_id, attempt),
        json.dumps({"run_id": run_id, "attempt": attempt}).encode(),
        content_type="application/json",
    )
    return attempt


def write_failure(
    store: ObjectStore,
    *,
    run_id: str,
    attempt: str,
    error: BaseException,
    n_traces: int,
    resumed: int,
) -> tuple[FailureRecord, str]:
    """Record that this attempt died, under a key of its own, and return the record and its key.

    Not the manifest, on purpose. `manifest.json` means the run closed, and the store only appends,
    so a failure written there would burn the run id: every later runner would read it as complete
    and do nothing, and the only way forward would be a new run against the assistant. Under its
    own key the record says what happened, the traces already paid for stay where they are, and the
    next attempt resumes from the difference exactly as after a kill.

    `attempt` is the id `begin_attempt` returned: the record lands under the same id as the marker,
    which is how the status knows this is the newest attempt's death and not an earlier one's.
    """
    from redteam_engine.errors import TargetFailure

    # A death of the channel carries its kind and the target's own words into the record, so the
    # reader knows what to fix -- a credential, a rate -- without opening a trace.
    typed = error if isinstance(error, TargetFailure) else None
    record = FailureRecord(
        run_id=run_id,
        attempt=attempt,
        error=f"{type(error).__name__}: {str(error)[:500]}",
        n_traces=n_traces,
        resumed=resumed,
        dataset=layout.dataset(run_id) if store.exists(layout.dataset(run_id)) else None,
        kind=typed.kind if typed is not None else getattr(error, "kind", None),
        failure=typed.failure if typed is not None else None,
    )
    key = layout.failure(run_id, attempt)
    store.put(key, record.model_dump_json(indent=2).encode(), content_type="application/json")
    return record, key


def _attempt_id() -> str:
    """Sortable by time, and distinct even for two failures within one clock tick."""
    return f"{datetime.now(UTC).strftime('%Y%m%dT%H%M%S.%f')}Z-{secrets.token_hex(3)}"


def read_spec(store: ObjectStore, run_id: str) -> dict[str, object]:
    return dict(json.loads(store.get(layout.spec(run_id))))
