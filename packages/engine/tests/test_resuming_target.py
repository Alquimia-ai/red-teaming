"""A resumed attempt profiles the whole plan: closed units from the store, pending ones live."""

from __future__ import annotations

from typing import Any

from gaussia.schemas.roastme import TargetResponse

from redteam_contracts.plan import Plan, PlannedProbe, expand
from redteam_engine.recording import Recorder
from redteam_engine.resume import live_units, recorded_responses
from redteam_store import layout
from redteam_store.memory import MemoryObjectStore
from redteam_store.resume import difference

RUN = "run-resume"
PROBES: dict[str, dict[str, Any]] = {
    "p1": {"id": "p1", "query": "one?", "hook": {"references": "Alpha", "doc": 0}},
    "p2": {"id": "p2", "query": "two?", "hook": {"references": "Beta", "doc": 1}},
    "p3": {"id": "p3", "query": "three?", "hook": {"references": "Gamma", "doc": 1}},
}


class _Live:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def send(self, query: str, session_id: str | None = None) -> TargetResponse:
        self.calls.append(query)
        return TargetResponse(content=f"live answer to {query}")


def _plan() -> Plan:
    return expand(
        RUN,
        [PlannedProbe(probe_id="p1", plugin="invented-entity"), PlannedProbe(probe_id="p2")],
        {"c": "u"},
        1,
    )


def test_a_conducted_trace_replays_its_last_answer_which_is_the_one_gaussia_graded() -> None:
    """Replaying the first would grade a resumed run on the opening the attacker was told not to
    press on."""
    from redteam_engine.planned import MANY_TURNS, Conversation

    store = MemoryObjectStore()
    units = list(_plan().units)
    closed = units[:1]
    conversation = Conversation(
        pairs=(
            ("one?", TargetResponse(content="the opening's answer")),
            ("press", TargetResponse(content="what the escalation obtained")),
        ),
        technique=MANY_TURNS,
        attacker="crescendo",
    )
    Recorder(store, RUN, PROBES).record(closed[0], "one?", conversation.final, conversation)

    recorded = recorded_responses(store, RUN, closed)

    assert recorded[(closed[0].attack_id, closed[0].replica_idx)].content == (
        "what the escalation obtained"
    )


def test_a_failed_exchange_is_not_closed_and_goes_live_again() -> None:
    """A failure marker rather than a trace: the unit is not among the closed, and the resuming
    target asks the assistant again."""
    store = MemoryObjectStore()
    units = list(_plan().units)
    Recorder(store, RUN, PROBES).record(
        units[0], "one?", TargetResponse(content="", failed=True, failure_reason="503")
    )

    diff = difference(store, Plan(run_id=RUN, units=tuple(units)))
    assert (diff.closed, diff.failed) == ((), (units[0],))
    assert recorded_responses(store, RUN, diff.closed) == {}
    assert live_units(units, {}) == units


def test_a_trace_holding_a_failed_turn_still_replays_as_failed() -> None:
    """A trace whose agent turn carries a failure is replayed as failed rather than as an empty
    success, which would grade silence as compliance."""
    from redteam_contracts.trace import Role, Trace, TraceLabels, Turn
    from redteam_store.codec import encode_trace

    store = MemoryObjectStore()
    unit = _plan().units[0]
    stored = Trace(
        trace_id=f"{unit.attack_id}-0",
        run_id=RUN,
        attack_id=unit.attack_id,
        replica_idx=0,
        probe_id=unit.probe_id,
        turns=(
            Turn(idx=0, role=Role.ATTACKER, content="one?"),
            Turn(idx=1, role=Role.AGENT, content="", failed=True, failure_reason="503"),
        ),
        labels=TraceLabels(),
    )
    store.put(layout.trace(RUN, unit.attack_id, 0), encode_trace(stored))

    [(_, replayed)] = recorded_responses(store, RUN, [unit]).items()

    assert replayed.failed is True
    assert replayed.failure_reason == "503"


def test_what_goes_live_includes_units_marked_failed_not_only_pending_ones() -> None:
    """A unit with a `.failed` marker has no recorded answer, so the resuming target sends it live.
    The recorder is built over this list so its positional cursor counts that unit; built over the
    pending units alone, the next unit's key would take its answer."""
    store = MemoryObjectStore()
    plan = expand(RUN, [PlannedProbe(probe_id=p) for p in ("p1", "p2", "p3")], {"c": "u"}, 1)
    closed, marked, pending = plan.units
    Recorder(store, RUN, PROBES).record(
        closed, PROBES[closed.probe_id]["query"], TargetResponse(content="closed")
    )
    store.put(layout.trace_failure(RUN, marked.attack_id, marked.replica_idx), b"")
    diff = difference(store, plan)
    assert (diff.closed, diff.failed, diff.pending) == ((closed,), (marked,), (pending,))

    live = live_units(plan.units, recorded_responses(store, RUN, diff.closed))

    assert live == [marked, pending]


def test_the_search_is_remembered_with_its_session_and_read_back_by_a_relaunch() -> None:
    """A search that ran is remembered with its session; one that failed is remembered too, with no
    session, because it also sent queries. Both outrank a relaunch's own "skipped"."""
    from redteam_engine.dataset import RoastDataset
    from redteam_engine.resume import remember_exploit, remembered_exploit
    from redteam_store.priors import EmptyPrior  # noqa: F401  -- the store package is importable

    store = MemoryObjectStore()
    assert remembered_exploit(store, RUN) == ({}, [])

    session = RoastDataset(
        session_id=f"{RUN}:exploit", assistant_id="a", context="c", conversation=[]
    )
    remember_exploit(store, RUN, {"exploit": "ran", "exploit_n_categories": "1"}, [session])
    components, kept = remembered_exploit(store, RUN)
    assert components == {"exploit": "ran", "exploit_n_categories": "1"}
    assert [s.session_id for s in kept] == [f"{RUN}:exploit"]

    failed_run = "run-failed-search"
    remember_exploit(store, failed_run, {"exploit": "failed: RuntimeError: 429"}, [])
    assert remembered_exploit(store, failed_run) == ({"exploit": "failed: RuntimeError: 429"}, [])
    assert store.exists(layout.searched(failed_run))
