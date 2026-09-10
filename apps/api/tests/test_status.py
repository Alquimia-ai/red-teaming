"""Run state, derived from which artifacts exist and from what the platform says about the
process."""

from __future__ import annotations

import pytest

from redteam_api.status import derive
from redteam_contracts.manifest import RunPhase
from redteam_dispatch import JobState
from redteam_store import layout
from redteam_store.memory import MemoryObjectStore

RUN = "run-1"
ATTACK = "a" * 32
FIRST, SECOND = "20260910T170000.000000Z-aaaaaa", "20260910T170500.000000Z-bbbbbb"


def _store_with(*keys: str) -> MemoryObjectStore:
    store = MemoryObjectStore()
    for key in keys:
        store.put(key, b"{}")
    return store


def test_the_phase_follows_the_artifacts_in_the_order_they_are_written() -> None:
    accepted = _store_with(layout.spec(RUN))
    generating = _store_with(layout.spec(RUN), layout.attempt(RUN, FIRST))
    pinned = _store_with(layout.spec(RUN), layout.attempt(RUN, FIRST), layout.probes(RUN))
    attacking = _store_with(layout.spec(RUN), layout.probes(RUN), layout.trace(RUN, ATTACK, 0))
    closed = _store_with(layout.spec(RUN), layout.probes(RUN), layout.manifest(RUN))

    assert derive(accepted, RUN, None, JobState.PENDING).phase is RunPhase.ACCEPTED
    assert derive(generating, RUN, None, JobState.RUNNING).phase is RunPhase.GENERATING
    assert derive(pinned, RUN, 4, JobState.RUNNING).phase is RunPhase.ATTACKING
    assert derive(attacking, RUN, 4, JobState.RUNNING).phase is RunPhase.ATTACKING
    assert derive(closed, RUN, 4, JobState.SUCCEEDED).phase is RunPhase.COMPLETE


def test_progress_is_counted_off_the_keys() -> None:
    store = _store_with(
        layout.spec(RUN),
        layout.probes(RUN),
        layout.trace(RUN, ATTACK, 0),
        layout.trace(RUN, ATTACK, 1),
        layout.trace_failure(RUN, "b" * 32, 0),
    )
    status = derive(store, RUN, 6, JobState.RUNNING)
    assert (status.closed, status.failed, status.pending) == (2, 1, 3)
    assert derive(store, RUN, None, JobState.RUNNING).pending is None


def test_a_failed_attempt_reads_failed_and_not_complete() -> None:
    """A record from a runner that left no attempt marker still reads `failed`: nothing says anyone
    came after it."""
    store = _store_with(
        layout.spec(RUN),
        layout.probes(RUN),
        layout.trace(RUN, ATTACK, 0),
        layout.failure(RUN, FIRST),
    )
    status = derive(store, RUN, 4, JobState.FAILED)
    assert status.phase is RunPhase.FAILED
    assert not status.stalled, "failed is its own answer; nothing is stalled about it"


def test_a_relaunch_that_has_begun_reads_its_own_phase_not_the_earlier_death() -> None:
    """A consumer's poll loop stops on `failed`. Attempt one's record must not hold the status there
    while attempt two is attacking -- the consumer would give up exactly when the retry policy
    resumed."""
    store = _store_with(
        layout.spec(RUN),
        layout.probes(RUN),
        layout.trace(RUN, ATTACK, 0),
        layout.attempt(RUN, FIRST),
        layout.failure(RUN, FIRST),
    )
    assert derive(store, RUN, 4, JobState.FAILED).phase is RunPhase.FAILED

    store.put(layout.attempt(RUN, SECOND), b"{}")
    assert derive(store, RUN, 4, JobState.RUNNING).phase is RunPhase.ATTACKING

    store.put(layout.failure(RUN, SECOND), b"{}")
    assert derive(store, RUN, 4, JobState.FAILED).phase is RunPhase.FAILED


def test_a_manifest_after_a_failure_reads_complete() -> None:
    store = _store_with(layout.spec(RUN), layout.failure(RUN, FIRST), layout.manifest(RUN))
    assert derive(store, RUN, 4, JobState.SUCCEEDED).phase is RunPhase.COMPLETE


@pytest.mark.parametrize("phase_keys", [(layout.attempt(RUN, FIRST),), (layout.probes(RUN),)])
@pytest.mark.parametrize("gone", [JobState.UNKNOWN, JobState.FAILED])
def test_a_run_under_way_with_no_process_behind_it_is_stalled(
    phase_keys: tuple[str, ...], gone: JobState
) -> None:
    """The store says generating or attacking; the platform says nothing is running it. Neither
    source can say that alone, and the remedy is a relaunch that resumes from the difference."""
    store = _store_with(layout.spec(RUN), *phase_keys)

    stalled = derive(store, RUN, None, gone)
    moving = derive(store, RUN, None, JobState.RUNNING)
    scheduling = derive(store, RUN, None, JobState.PENDING)

    assert stalled.stalled and stalled.phase in (RunPhase.GENERATING, RunPhase.ATTACKING)
    assert not moving.stalled and not scheduling.stalled


def test_a_run_that_is_not_under_way_is_never_stalled() -> None:
    accepted = _store_with(layout.spec(RUN))
    closed = _store_with(layout.spec(RUN), layout.manifest(RUN))
    assert not derive(accepted, RUN, None, JobState.UNKNOWN).stalled
    assert not derive(closed, RUN, 4, JobState.UNKNOWN).stalled


def test_an_unknown_run_is_a_key_error() -> None:
    with pytest.raises(KeyError):
        derive(MemoryObjectStore(), RUN, None, JobState.UNKNOWN)
