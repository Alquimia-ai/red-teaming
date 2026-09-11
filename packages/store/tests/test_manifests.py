"""`manifest.json` means COMPLETE, is written once, and reads back whole."""

from __future__ import annotations

import pytest

from redteam_contracts.manifest import Coverage, CoverageReport, RunPhase
from redteam_store import layout, manifests
from redteam_store.interface import ObjectAlreadyExists
from redteam_store.memory import MemoryObjectStore


def _write(store: MemoryObjectStore) -> None:
    manifests.write(
        store,
        run_id="run-1",
        spec_digest="sha256:spec",
        probes_digest="sha256:probes",
        dataset=layout.dataset("run-1"),
        profile=layout.profile("run-1"),
        exploit=None,
        n_total_traces=4,
        coverage=CoverageReport(total=Coverage(planned=4, closed=4, failed=0)),
        components={"target": "replay"},
    )


def test_a_run_that_has_not_closed_has_no_manifest() -> None:
    assert manifests.read(MemoryObjectStore(), "run-1") is None


def test_the_manifest_is_complete_by_construction_and_reads_back() -> None:
    store = MemoryObjectStore()
    _write(store)

    manifest = manifests.read(store, "run-1")

    assert manifest is not None
    assert manifest.phase is RunPhase.COMPLETE
    assert manifest.profile == "runs/run-1/profile.json" and manifest.exploit is None
    assert manifest.coverage.total.pending == 0


def test_the_manifest_is_the_run_s_last_word() -> None:
    store = MemoryObjectStore()
    _write(store)
    with pytest.raises(ObjectAlreadyExists):
        _write(store)
