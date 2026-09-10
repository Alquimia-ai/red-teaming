"""Each exchange is written the instant it closes, under the key the plan gave it."""

from __future__ import annotations

from typing import Any

from gaussia.schemas.roastme import TargetResponse

from redteam_contracts.failure import RATE_LIMITED, SERVER_ERROR, TransportFailure
from redteam_contracts.plan import Plan, PlannedProbe, expand
from redteam_engine.planned import STATIC_TECHNIQUE
from redteam_engine.recording import EXPLOIT, Recorder
from redteam_engine.resume import live_units, recorded_responses
from redteam_store import layout
from redteam_store.codec import decode_trace
from redteam_store.memory import MemoryObjectStore
from redteam_store.resume import difference
from redteam_target.failures import failed_response

RUN = "run-rec"
PROBES: dict[str, dict[str, Any]] = {
    "p1": {
        "id": "p1",
        "query": "one?",
        "strategy": "ask-fake",
        "plugin": "invented-entity",
        "hook": {"references": "Alpha", "doc": 0, "principle": "no_invention"},
    },
    "p2": {
        "id": "p2",
        "query": "two?",
        "strategy": "ask-real",
        "plugin": "invented-entity",
        "hook": {"references": "Beta", "doc": 1, "principle": "no_invention"},
    },
}


def _planned(probe_id: str) -> PlannedProbe:
    probe = PROBES[probe_id]
    return PlannedProbe(probe_id=probe_id, plugin=probe["plugin"], strategy=probe["strategy"])


def _plan(replicas: int = 2) -> Plan:
    return expand(RUN, [_planned("p1"), _planned("p2")], {"c": "u"}, replicas)


def test_the_kth_exchange_lands_under_the_kth_pending_unit() -> None:
    """Positional, on purpose: mapping by query text breaks the day two strategies phrase the same
    question, which a catalogue is free to do."""
    store = MemoryObjectStore()
    plan = _plan()
    recorder = Recorder(store, RUN, plan.units, PROBES)

    for unit in plan.units:
        recorder(PROBES[unit.probe_id]["query"], TargetResponse(content="ok"))

    for unit in plan.units:
        key = layout.trace(RUN, unit.attack_id, unit.replica_idx)
        assert store.exists(key), f"{key} was not written"
        trace = decode_trace(store.get(key))
        assert trace.replica_idx == unit.replica_idx
        assert trace.probe_id == unit.probe_id
        assert trace.labels.plugin == "invented-entity"
        assert trace.labels.strategy == PROBES[unit.probe_id]["strategy"]
        assert trace.labels.principle == "no_invention"
        assert trace.labels.attacked_entity == PROBES[unit.probe_id]["hook"]["references"]
        assert trace.labels.orchestration_technique == STATIC_TECHNIQUE
        assert trace.labels.turn_depth == 1
    assert recorder.written == len(plan.units)
    assert recorder.beyond_plan == 0


def test_a_conducted_conversation_is_one_trace_carrying_every_turn() -> None:
    """One unit, one key, and the whole exchange under it: turns in order, the depth the agent
    answered to, who steered it and why it stopped. The next attempt replays its last answer."""
    from redteam_engine.planned import ENDED_BY_ATTACKER, MANY_TURNS, Conversation

    store = MemoryObjectStore()
    plan = _plan(replicas=1)
    recorder = Recorder(store, RUN, plan.units, PROBES)
    unit = plan.units[0]
    conversation = Conversation(
        pairs=(
            ("one?", TargetResponse(content="first answer", session_id="s-1")),
            ("say more", TargetResponse(content="second answer", session_id="s-1")),
            ("and the rest", TargetResponse(content="final answer", session_id="s-1")),
        ),
        technique=MANY_TURNS,
        attacker="crescendo",
        session_id="s-1",
        ended=ENDED_BY_ATTACKER,
    )

    recorder("one?", conversation.final, conversation)

    trace = decode_trace(store.get(layout.trace(RUN, unit.attack_id, unit.replica_idx)))
    assert [(t.idx, t.role.value, t.content) for t in trace.turns] == [
        (0, "attacker", "one?"),
        (1, "agent", "first answer"),
        (2, "attacker", "say more"),
        (3, "agent", "second answer"),
        (4, "attacker", "and the rest"),
        (5, "agent", "final answer"),
    ]
    assert trace.labels.turn_depth == 3
    assert trace.labels.orchestration_technique == MANY_TURNS
    assert trace.labels.attacker == "crescendo"
    assert trace.labels.session_id == "s-1"
    assert trace.labels.ended == ENDED_BY_ATTACKER
    assert trace.agent_turns[-1].content == "final answer"


def test_a_conversation_whose_last_turn_failed_marks_the_unit_and_writes_nothing_partial() -> None:
    """The turns before it were answered, but the unit was not; the next attempt conducts it
    again."""
    from redteam_engine.planned import ENDED_BY_TARGET_FAILURE, MANY_TURNS, Conversation

    store = MemoryObjectStore()
    plan = _plan(replicas=1)
    recorder = Recorder(store, RUN, plan.units, PROBES)
    unit = plan.units[0]
    failed = failed_response(TransportFailure(kind=SERVER_ERROR, message="500", error_type="500"))
    conversation = Conversation(
        pairs=(("one?", TargetResponse(content="first")), ("more", failed)),
        technique=MANY_TURNS,
        attacker="crescendo",
        ended=ENDED_BY_TARGET_FAILURE,
    )

    recorder("one?", failed, conversation)

    assert not store.exists(layout.trace(RUN, unit.attack_id, unit.replica_idx))
    assert store.exists(layout.trace_failure(RUN, unit.attack_id, unit.replica_idx))
    assert recorder.failed == 1


def test_only_the_pending_units_are_handed_over_and_the_indices_still_match() -> None:
    """Resumption: the Profiler is given the pending units in plan order, so replica 1 of a probe
    whose replica 0 already closed still lands under replica 1."""
    store = MemoryObjectStore()
    plan = _plan(replicas=2)
    pending = [u for u in plan.units if u.replica_idx == 1]
    recorder = Recorder(store, RUN, pending, PROBES)

    for unit in pending:
        recorder(PROBES[unit.probe_id]["query"], TargetResponse(content="ok"))

    for unit in pending:
        assert store.exists(layout.trace(RUN, unit.attack_id, 1))
        assert not store.exists(layout.trace(RUN, unit.attack_id, 0))


def test_an_already_closed_key_is_left_alone() -> None:
    """Another attempt closed it first. The store is the record, and the record says done."""
    store = MemoryObjectStore()
    plan = _plan(replicas=1)
    Recorder(store, RUN, plan.units, PROBES)("one?", TargetResponse(content="first"))
    Recorder(store, RUN, plan.units, PROBES)("one?", TargetResponse(content="second"))

    unit = plan.units[0]
    assert decode_trace(store.get(layout.trace(RUN, unit.attack_id, 0))).turns[1].content == "first"


def test_the_search_s_own_conversations_are_evidence_beyond_the_plan() -> None:
    """Keyed by content, aimed at no plugin: evidence, never coverage. Exactly the distinction the
    coverage report exists to draw."""
    store = MemoryObjectStore()
    recorder = Recorder(store, RUN, [], PROBES)
    recorder.phase = EXPLOIT
    recorder("a generated question?", TargetResponse(content="an answer"))

    [key] = store.list_prefix(layout.traces_prefix(RUN) + "/")
    trace = decode_trace(store.get(key))
    assert trace.labels.plugin is None and trace.labels.strategy is None
    assert trace.labels.principle is None
    assert trace.labels.orchestration_technique == STATIC_TECHNIQUE
    assert trace.probe_id == "exploit-generated"
    assert recorder.beyond_plan == 1


def test_a_failed_exchange_marks_the_unit_failed_and_leaves_it_for_the_next_attempt() -> None:
    """Written under the planned key, the unit would read as closed: never retried, replayed into
    the judge on every resume, counted against the profile again each time. The marker keeps the
    evidence and reopens the unit."""
    store = MemoryObjectStore()
    plan = _plan(replicas=1)
    recorder = Recorder(store, RUN, plan.units, PROBES)
    failure = TransportFailure(kind=RATE_LIMITED, message="slow down", error_type="X", status=429)

    recorder("one?", failed_response(failure))
    recorder("two?", TargetResponse(content="fine"))

    first, second = plan.units
    assert not store.exists(layout.trace(RUN, first.attack_id, 0))
    marker = store.get(layout.trace_failure(RUN, first.attack_id, 0))
    assert TransportFailure.model_validate_json(marker) == failure
    assert store.exists(layout.trace(RUN, second.attack_id, 0)), "the cursor still advanced"
    assert (recorder.written, recorder.failed) == (1, 1)

    diff = difference(store, plan)
    assert (diff.closed, diff.failed, diff.pending) == ((second,), (first,), ())
    assert live_units(plan.units, recorded_responses(store, RUN, diff.closed)) == [first]


def test_a_marker_from_an_earlier_attempt_is_left_alone() -> None:
    store = MemoryObjectStore()
    plan = _plan(replicas=1)
    unit = plan.units[0]
    store.put(layout.trace_failure(RUN, unit.attack_id, 0), b"an earlier attempt's record")
    recorder = Recorder(store, RUN, plan.units, PROBES)

    recorder("one?", TargetResponse(content="", failed=True, failure_reason="again"))

    assert store.get(layout.trace_failure(RUN, unit.attack_id, 0)) == b"an earlier attempt's record"
    assert recorder.failed == 0


def test_a_failed_conversation_beyond_the_plan_is_a_trace_carrying_the_record() -> None:
    """The search's own conversation has no unit to reopen, so the evidence is written as a trace
    and the turn carries what went wrong."""
    store = MemoryObjectStore()
    recorder = Recorder(store, RUN, [], PROBES)
    recorder.phase = EXPLOIT
    failure = TransportFailure(kind=SERVER_ERROR, message="oops", error_type="X", status=500)

    recorder("a generated question?", failed_response(failure))

    [key] = store.list_prefix(layout.traces_prefix(RUN) + "/")
    turn = decode_trace(store.get(key)).turns[1]
    assert turn.failed and turn.failure == failure
