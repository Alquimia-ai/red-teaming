"""The manifest: written by whoever closes the run, read by everybody.

One rule: **`manifest.json` means COMPLETE and nothing else writes it.** An attempt that dies writes
a `FailureRecord` under its own key, because the store only appends and a failure written here would
burn the run id.
"""

from __future__ import annotations

from redteam_contracts.manifest import CoverageReport, Manifest, RunPhase
from redteam_store import layout
from redteam_store.interface import ObjectNotFound, ObjectStore


def write(
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

    Only a run that closed gets here: the phase is COMPLETE by construction.
    """
    manifest = Manifest(
        run_id=run_id,
        phase=RunPhase.COMPLETE,
        spec_digest=spec_digest,
        probes_digest=probes_digest,
        dataset=dataset,
        profile=profile,
        exploit=exploit,
        n_total_traces=n_total_traces,
        coverage=coverage,
        components=components,
    )
    store.put(
        layout.manifest(run_id),
        manifest.model_dump_json(indent=2).encode(),
        content_type="application/json",
    )
    return manifest


def read(store: ObjectStore, run_id: str) -> Manifest | None:
    """The run's manifest, or `None` while it has not closed.

    `None` rather than a raise, because "has this run closed" is an ordinary question and the answer
    is often no. A caller that crashed between closing a run and delivering it asks this on the way
    back, and the manifest standing is what makes that recovery a delivery rather than a second
    attack.
    """
    try:
        return Manifest.model_validate_json(store.get(layout.manifest(run_id)))
    except ObjectNotFound:
        return None
