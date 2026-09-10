"""Closing a run: the manifest means complete, and a failure is written somewhere else."""

from __future__ import annotations

from redteam_contracts.manifest import Coverage, CoverageReport, FailureRecord, RunPhase
from redteam_engine.assemble import begin_attempt, write_failure, write_manifest
from redteam_store import layout
from redteam_store.memory import MemoryObjectStore


def test_an_attempt_announces_itself_and_its_record_carries_the_same_id() -> None:
    """The marker is what lets the status tell "the newest attempt died" from "an earlier one did":
    a failure record alone reads `failed` for the whole life of the relaunch."""
    store = MemoryObjectStore()

    attempt = begin_attempt(store, run_id="r")
    record, key = write_failure(
        store, run_id="r", attempt=attempt, error=RuntimeError("boom"), n_traces=0, resumed=0
    )

    assert store.exists(layout.attempt("r", attempt))
    assert key == layout.failure("r", attempt)
    assert record.attempt == attempt


def test_a_failure_is_recorded_under_its_own_key_and_never_as_the_manifest() -> None:
    """The store only appends, so a failure written as the manifest would be the run's last word."""
    store = MemoryObjectStore()

    record, key = write_failure(
        store, run_id="r", attempt="a1", error=RuntimeError("boom"), n_traces=3, resumed=1
    )

    assert key.startswith(layout.failures_prefix("r") + "/")
    assert not store.exists(layout.manifest("r")), "a failed attempt burned the run id"
    loaded = FailureRecord.model_validate_json(store.get(key))
    assert loaded == record
    assert loaded.error == "RuntimeError: boom"
    assert (loaded.n_traces, loaded.resumed, loaded.dataset) == (3, 1, None)
    assert loaded.kind is None and loaded.failure is None


def test_a_death_of_the_channel_carries_its_kind_into_the_record() -> None:
    from http import HTTPStatus

    from redteam_contracts.failure import UNAUTHORIZED, TransportFailure
    from redteam_engine.errors import error_for

    store = MemoryObjectStore()
    failure = TransportFailure(
        kind=UNAUTHORIZED, message="bad key", error_type="X", status=HTTPStatus.UNAUTHORIZED
    )

    record, _ = write_failure(
        store, run_id="r", attempt="a1", error=error_for(failure), n_traces=2, resumed=0
    )

    assert record.kind == UNAUTHORIZED
    assert record.failure == failure
    assert record.error.startswith("TargetUnauthorized: unauthorized: HTTP 401")


def test_every_failed_attempt_keeps_its_own_record() -> None:
    store = MemoryObjectStore()
    _, first = write_failure(
        store, run_id="r", attempt="a1", error=ValueError("a"), n_traces=1, resumed=0
    )
    _, second = write_failure(
        store, run_id="r", attempt="a2", error=ValueError("b"), n_traces=2, resumed=1
    )

    assert first != second
    assert store.list_prefix(layout.failures_prefix("r") + "/") == sorted([first, second])


def test_the_failure_record_points_at_the_dataset_when_one_was_written() -> None:
    store = MemoryObjectStore()
    store.put(layout.dataset("r"), b"[]")
    record, _ = write_failure(
        store, run_id="r", attempt="a1", error=RuntimeError("x"), n_traces=0, resumed=0
    )
    assert record.dataset == layout.dataset("r")


def test_the_manifest_is_always_complete_and_names_the_control_artifacts() -> None:
    store = MemoryObjectStore()
    coverage = CoverageReport(total=Coverage(planned=2, closed=2, failed=0))
    manifest = write_manifest(
        store,
        run_id="r",
        spec_digest="spec",
        probes_digest=None,
        dataset=layout.dataset("r"),
        profile=layout.profile("r"),
        exploit=None,
        n_total_traces=2,
        coverage=coverage,
        components={"exploit": "skipped: not declared -- generator"},
    )
    assert manifest.phase is RunPhase.COMPLETE
    assert manifest.profile == "runs/r/profile.json" and manifest.exploit is None
    assert manifest.coverage.total.pending == 0
    assert store.exists(layout.manifest("r"))
