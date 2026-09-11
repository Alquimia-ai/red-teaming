"""Resumption: the difference between the plan and the store, and nothing else."""

from __future__ import annotations

from redteam_contracts.plan import Plan, PlannedProbe, WorkUnit, expand
from redteam_store import layout
from redteam_store.interface import ObjectAlreadyExists
from redteam_store.memory import MemoryObjectStore
from redteam_store.resume import difference

RUN = "run-1"
PROBES = [
    PlannedProbe(probe_id="p1", plugin="invention", strategy="ask-fake"),
    PlannedProbe(probe_id="p2", plugin="disclosure", strategy="ask-prompt"),
    PlannedProbe(probe_id="p3", plugin=None, strategy="ask-scope"),
]
PARAMS = {"strategy": "keep_real"}


def _plan(replicas: int = 2) -> Plan:
    return expand(RUN, PROBES, PARAMS, replicas)


def _close(store: MemoryObjectStore, unit: WorkUnit) -> None:
    store.put(layout.trace(RUN, unit.attack_id, unit.replica_idx), b"{}\n")


def test_a_fresh_run_is_entirely_pending() -> None:
    plan = _plan()
    diff = difference(MemoryObjectStore(), plan)
    assert diff.pending == plan.units
    assert not diff.closed and not diff.failed
    assert not diff.is_complete


def test_closed_units_are_never_re_executed() -> None:
    plan = _plan()
    store = MemoryObjectStore()
    _close(store, plan.units[0])
    _close(store, plan.units[2])

    diff = difference(store, plan)
    assert set(diff.closed) == {plan.units[0], plan.units[2]}
    assert set(diff.pending) == set(plan.units) - {plan.units[0], plan.units[2]}


def test_a_run_is_complete_when_the_difference_is_empty() -> None:
    plan = _plan()
    store = MemoryObjectStore()
    for unit in plan.units:
        _close(store, unit)
    assert difference(store, plan).is_complete


def test_a_failure_marker_is_not_the_same_as_never_having_run() -> None:
    """Listing says what is there, not why what is missing is missing."""
    plan = _plan()
    store = MemoryObjectStore()
    unit = plan.units[0]
    store.put(layout.trace_failure(RUN, unit.attack_id, unit.replica_idx), b"budget exhausted")

    diff = difference(store, plan)
    assert diff.failed == (unit,)
    assert unit not in diff.pending


def test_a_restarted_runner_reaches_the_same_place() -> None:
    """The property the whole scheme rests on: none of the three arrows depends on memory of the
    previous attempt."""
    plan = _plan(replicas=3)
    store = MemoryObjectStore()

    first_pass = difference(store, plan).pending[:4]
    for unit in first_pass:
        _close(store, unit)

    # a brand new plan object, as a restarted process would build
    resumed = difference(store, expand(RUN, PROBES, PARAMS, 3))
    assert set(resumed.closed) == set(first_pass)
    assert len(resumed.pending) == len(plan.units) - 4


def test_the_store_refuses_to_overwrite_evidence() -> None:
    plan = _plan()
    store = MemoryObjectStore()
    _close(store, plan.units[0])
    try:
        _close(store, plan.units[0])
    except ObjectAlreadyExists as exc:
        assert plan.units[0].attack_id in exc.key
    else:
        raise AssertionError("the store overwrote a closed trace")


def test_coverage_is_the_same_difference_sliced_by_plugin_and_strategy() -> None:
    """Planned, closed and failed come from the same keys resumption reads, so they cannot
    disagree with what the store holds. A control counts in the total and its strategy only."""
    plan = _plan(replicas=2)
    store = MemoryObjectStore()
    by_probe = {u.probe_id: [x for x in plan.units if x.probe_id == u.probe_id] for u in plan.units}
    _close(store, by_probe["p1"][0])
    _close(store, by_probe["p1"][1])
    _close(store, by_probe["p3"][0])
    p2 = by_probe["p2"][0]
    store.put(layout.trace_failure(RUN, p2.attack_id, p2.replica_idx), b"unauthorized")

    coverage = difference(store, plan).coverage()

    assert (coverage.total.planned, coverage.total.closed, coverage.total.failed) == (6, 3, 1)
    assert coverage.total.pending == 2
    assert set(coverage.by_plugin) == {"invention", "disclosure"}
    assert coverage.by_plugin["invention"].closed == 2
    assert coverage.by_plugin["disclosure"].failed == 1
    assert coverage.by_plugin["disclosure"].pending == 1
    assert coverage.by_strategy["ask-scope"].closed == 1
    assert coverage.by_strategy["ask-scope"].planned == 2
