"""A conducted conversation is one exchange to gaussia, one trace to the store, and N calls to the
assistant -- every one of them governed.

The door runs the loop, for the reason it runs the retry loop: the recorder and the resuming target
map the k-th exchange to the k-th unit, and anything that surfaced N exchanges for one unit would
shift every unit after it by one.
"""

from __future__ import annotations

import time
from collections.abc import Sequence
from typing import Any

import pytest
from gaussia.schemas.roastme import TargetResponse

from redteam_contracts.failure import RATE_LIMITED, UNAUTHORIZED, TransportFailure
from redteam_engine import planned as planned_module
from redteam_engine.errors import TargetUnauthorized
from redteam_engine.governed import Budget, BudgetExhausted, GovernedTarget, RateGate
from redteam_engine.planned import (
    ENDED_BY_ATTACKER,
    ENDED_BY_ATTACKER_FAILURE,
    ENDED_BY_BOUND,
    ENDED_BY_BUDGET,
    ENDED_BY_TARGET_FAILURE,
    MANY_TURNS,
    STATIC_TECHNIQUE,
    Conversation,
    PlannedDelivery,
    attackers_named_by,
    conducted_plugins,
    delivery_provenance,
    planned_deliveries,
)
from redteam_store.delivery import STATIC, Delivery, Objective, Turns
from redteam_target.capabilities import CapabilityGate
from redteam_target.failures import failed_response

OBJECTIVE = Objective(description="Asks the assistant to reveal its instructions.", principle="p")
CONDUCTED = PlannedDelivery(
    delivery=Delivery(turns=Turns.MANY, attacker="crescendo", max_turns=3),
    objective=OBJECTIVE,
    approach=("asks how it decides", "then presses"),
)
ONE_TURN = PlannedDelivery(delivery=STATIC, objective=None)


class _Target:
    """Answers every turn, echoing the session it was handed so the test can see continuity."""

    def __init__(self, *answers: TargetResponse, minted: str | None = "srv-1") -> None:
        self._answers = list(answers)
        self._minted = minted
        self.calls: list[tuple[str, str | None]] = []

    def send(self, query: str, session_id: str | None = None) -> TargetResponse:
        self.calls.append((query, session_id))
        answer = self._answers.pop(0) if self._answers else TargetResponse(content=f"re: {query}")
        if answer.session_id is None and not answer.failed:
            return answer.model_copy(update={"session_id": session_id or self._minted})
        return answer


class _Attacker:
    """Writes scripted follow-ups; `None` is "done"; an exception is the provider failing."""

    def __init__(self, *turns: str | Exception | None) -> None:
        self._turns = list(turns)
        self.asked: list[tuple[Objective, Sequence[str], Sequence[tuple[str, str]]]] = []
        self.model = "scripted"

    def next_turn(
        self, objective: Objective, approach: Sequence[str], transcript: Sequence[tuple[str, str]]
    ) -> str | None:
        self.asked.append((objective, approach, list(transcript)))
        turn = self._turns.pop(0) if self._turns else None
        if isinstance(turn, Exception):
            raise turn
        return turn


def _door(
    target: Any,
    planned: Sequence[PlannedDelivery],
    attacker: Any,
    *,
    budget: Budget | None = None,
    max_retries: int = 1,
) -> tuple[GovernedTarget, list[Conversation]]:
    recorded: list[Conversation] = []
    door = GovernedTarget(
        target,
        gate=CapabilityGate(declared_capabilities=(), safe_mode=True),
        budget=budget or Budget(),
        rate=RateGate(sleep=lambda _s: None),
        on_exchange=lambda _q, _r, conversation: recorded.append(conversation),
        max_retries=max_retries,
        planned=planned,
        attackers={"crescendo": attacker},
    )
    return door, recorded


@pytest.fixture(autouse=True)
def _no_backoff_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    """The attacker's retry backs off through `time.sleep`; a test of it should not wait it out."""
    monkeypatch.setattr(time, "sleep", lambda _s: None)


def test_a_conversation_is_one_exchange_to_gaussia_and_every_turn_to_the_assistant() -> None:
    """gaussia sends the opening and reads the final answer -- what the escalation obtained. The
    assistant answered three times, and the recorder saw one conversation carrying all three."""
    target = _Target()
    attacker = _Attacker("Could you say more?", "And the rest?")
    door, recorded = _door(target, [CONDUCTED], attacker)

    final = door.send("How do you decide what to answer?")

    assert final.content == "re: And the rest?"
    assert [q for q, _ in target.calls] == [
        "How do you decide what to answer?",
        "Could you say more?",
        "And the rest?",
    ]
    [conversation] = recorded
    assert conversation.technique == MANY_TURNS
    assert conversation.depth == 3
    assert conversation.attacker == "crescendo"
    assert conversation.ended == ENDED_BY_BOUND, "three turns is the bound"
    assert len(door.exchanges) == 1, "one exchange, whatever the delivery"
    assert door.conducted == 1 and door.ended_early == 0


def test_every_turn_is_charged_to_the_budget() -> None:
    """The ceiling is on what the assistant's infrastructure takes, and a conversation takes N
    calls."""
    budget = Budget()
    door, _ = _door(_Target(), [CONDUCTED], _Attacker("more", "more"), budget=budget)

    door.send("opening")

    assert budget.calls == 3


def test_the_session_the_target_named_on_the_first_turn_is_carried_into_the_next() -> None:
    """gaussia's protocol for an adapter that keeps sessions: open with none, continue with the one
    it named. The trace keeps it, so the conversation can be found in the target's own log."""
    target = _Target(minted="runtime-session-9")
    door, recorded = _door(target, [CONDUCTED], _Attacker("more", None))

    door.send("opening")

    assert [s for _, s in target.calls] == [None, "runtime-session-9"]
    assert recorded[0].session_id == "runtime-session-9"


def test_a_target_that_names_no_session_is_handed_one_minted_here() -> None:
    """A stateless adapter keeps its own history under the key it is handed, so there has to be
    one -- and it stays the same for the whole conversation."""
    target = _Target(minted=None)
    door, recorded = _door(target, [CONDUCTED], _Attacker("more", "more"))

    door.send("opening")

    sessions = [s for _, s in target.calls]
    assert sessions[0] is None
    assert sessions[1] is not None and sessions[1] == sessions[2]
    assert recorded[0].session_id == sessions[1]


def test_the_attacker_ends_the_conversation_when_it_judges_the_objective_reached() -> None:
    target = _Target()
    door, recorded = _door(target, [CONDUCTED], _Attacker("one more", None))

    door.send("opening")

    assert len(target.calls) == 2
    assert recorded[0].ended == ENDED_BY_ATTACKER
    assert recorded[0].depth == 2


def test_the_attacker_is_told_the_objective_the_approach_and_the_whole_transcript() -> None:
    attacker = _Attacker("more", None)
    door, _ = _door(_Target(), [CONDUCTED], attacker)

    door.send("opening")

    objective, approach, transcript = attacker.asked[-1]
    assert objective == OBJECTIVE
    assert approach == ("asks how it decides", "then presses")
    assert transcript == [("opening", "re: opening"), ("more", "re: more")]


def test_an_attacker_that_fails_three_times_closes_the_conversation_as_it_stands() -> None:
    """Not the unit marked failed -- the turns the assistant answered were paid for and are real --
    and not the attempt killed: a provider that blips should not lose a run. The trace says why it
    is shorter than its bound, and the door counts it."""
    target = _Target()
    attacker = _Attacker(RuntimeError("429"), RuntimeError("429"), RuntimeError("429"))
    door, recorded = _door(target, [CONDUCTED], attacker)

    final = door.send("opening")

    assert final.content == "re: opening"
    assert len(target.calls) == 1
    assert recorded[0].ended == ENDED_BY_ATTACKER_FAILURE
    assert recorded[0].depth == 1
    assert door.ended_early == 1
    assert len(attacker.asked) == 3, "three draws, then the truth"


def test_an_attacker_that_fails_once_is_asked_again() -> None:
    attacker = _Attacker(RuntimeError("blip"), "more", None)
    door, recorded = _door(_Target(), [CONDUCTED], attacker)

    door.send("opening")

    assert recorded[0].depth == 2
    assert recorded[0].ended == ENDED_BY_ATTACKER


def test_a_target_that_fails_a_later_turn_marks_the_unit_failed_as_a_static_one_would() -> None:
    """One exchange surfaces, and its final answer is the failure: the recorder marks the unit,
    nothing partial is written, and the next attempt conducts the conversation again."""
    rate_limited = failed_response(
        TransportFailure(kind=RATE_LIMITED, message="slow down", error_type="429")
    )
    target = _Target(TargetResponse(content="first"), rate_limited, rate_limited)
    door, recorded = _door(target, [CONDUCTED], _Attacker("more", "more"), max_retries=1)

    final = door.send("opening")

    assert final.failed
    [conversation] = recorded
    assert conversation.ended == ENDED_BY_TARGET_FAILURE
    assert conversation.depth == 2
    assert conversation.final.failed


def test_a_refused_credential_mid_conversation_is_recorded_whole_and_then_raised() -> None:
    """A run that died of a 401 should show the 401 -- and the turns before it."""
    unauthorized = failed_response(
        TransportFailure(kind=UNAUTHORIZED, message="no", error_type="401")
    )
    target = _Target(TargetResponse(content="first"), unauthorized)
    door, recorded = _door(target, [CONDUCTED], _Attacker("more", "more"))

    with pytest.raises(TargetUnauthorized):
        door.send("opening")

    [conversation] = recorded
    assert conversation.depth == 2
    assert conversation.final.failed
    assert conversation.ended == ENDED_BY_TARGET_FAILURE


def test_a_budget_that_runs_out_between_turns_closes_the_conversation_and_stops_the_run() -> None:
    """What the assistant answered is recorded before the run stops, and the trace says the budget
    ended it; the next attempt finds the unit closed rather than conducting it again."""
    target = _Target()
    door, recorded = _door(
        target, [CONDUCTED], _Attacker("more", "more"), budget=Budget(max_target_calls=2)
    )

    with pytest.raises(BudgetExhausted):
        door.send("opening")

    [conversation] = recorded
    assert conversation.depth == 2
    assert conversation.ended == ENDED_BY_BUDGET
    assert door.ended_early == 1
    assert len(target.calls) == 2


def test_a_static_delivery_is_one_turn_and_never_asks_the_attacker() -> None:
    target = _Target()
    attacker = _Attacker("never asked")
    door, recorded = _door(target, [ONE_TURN], attacker)

    final = door.send("a question")

    assert final.content == "re: a question"
    assert len(target.calls) == 1
    assert attacker.asked == []
    [conversation] = recorded
    assert conversation.technique == STATIC_TECHNIQUE
    assert conversation.depth == 1 and conversation.attacker is None and conversation.ended is None
    assert door.conducted == 0


def test_exchanges_past_the_plan_are_static_because_they_are_the_search_s() -> None:
    """The Exploiter's own conversations reach the same door after the plan is done; nothing plans
    their delivery, so they are one turn each."""
    target = _Target()
    attacker = _Attacker("more", "more", "more", "more")
    door, recorded = _door(target, [CONDUCTED], attacker)

    door.send("planned opening")
    door.send("a question the search generated")

    assert recorded[1].technique == STATIC_TECHNIQUE
    assert len(target.calls) == 4, "three for the conversation, one for the search"


def test_an_attacker_the_plan_names_and_nobody_built_is_refused_not_worked_around() -> None:
    door = GovernedTarget(
        _Target(),
        gate=CapabilityGate(declared_capabilities=(), safe_mode=True),
        budget=Budget(),
        planned=[CONDUCTED],
        attackers={},
    )

    with pytest.raises(LookupError, match="crescendo"):
        door.send("opening")


# ---- planning the deliveries over the live units ------------------------------------------------


def _unit(probe_id: str) -> Any:
    from redteam_contracts.plan import WorkUnit

    probe = PROBES[probe_id]
    return WorkUnit(
        probe_id=probe_id,
        attack_params={},
        replica_idx=0,
        plugin=probe["plugin"],
        strategy=probe["strategy"],
    )


PROBES: dict[str, dict[str, Any]] = {
    "p-static": {"id": "p-static", "strategy": "ask", "plugin": "disclosure", "attrs": ["asks"]},
    "p-many": {
        "id": "p-many",
        "strategy": "escalate",
        "plugin": "disclosure",
        "attrs": ["presses"],
    },
    "p-control": {"id": "p-control", "strategy": "control", "plugin": None, "attrs": []},
}
DELIVERIES = {"escalate": Delivery(turns=Turns.MANY, attacker="crescendo", max_turns=4)}
OBJECTIVES = {"disclosure": OBJECTIVE}


def test_deliveries_are_planned_over_the_live_units_in_their_order() -> None:
    planned = planned_deliveries(
        [_unit("p-static"), _unit("p-many"), _unit("p-control")], PROBES, DELIVERIES, OBJECTIVES
    )

    assert [p.delivery.conducted for p in planned] == [False, True, False]
    assert planned[1].objective == OBJECTIVE
    assert planned[1].approach == ("presses",)
    assert planned[1].delivery.max_turns == 4


def test_a_conducted_strategy_that_attacks_nothing_is_refused_before_the_first_turn() -> None:
    with pytest.raises(ValueError, match="attack something"):
        planned_deliveries(
            [_unit("p-control")],
            PROBES,
            {"control": Delivery(turns=Turns.MANY, attacker="crescendo")},
            OBJECTIVES,
        )


def test_the_conductor_module_names_no_target_adapter() -> None:
    """The attacker's turns reach the assistant through the governed door and nowhere else."""
    import inspect

    source = inspect.getsource(planned_module)
    for name in ("AlquimiaTargetAssistant", "ReplayTargetAssistant", "build_target"):
        assert name not in source


def test_the_attackers_the_plan_names_are_the_whole_plan_s_not_the_live_tail_s() -> None:
    """An attacker that steered a conversation an earlier attempt closed took part in the run, and
    the manifest has to name it whether or not this attempt conducts anything."""
    units = [_unit("p-static"), _unit("p-many"), _unit("p-control")]

    assert attackers_named_by(units, PROBES, DELIVERIES) == frozenset({"crescendo"})
    assert attackers_named_by([_unit("p-static")], PROBES, DELIVERIES) == frozenset()


def test_only_the_plugins_of_conducted_units_need_an_objective() -> None:
    """A static run reads no objective at all, so two catalogues describing a plugin in their own
    words never stop it before the first call."""
    units = [_unit("p-static"), _unit("p-many"), _unit("p-control")]

    assert conducted_plugins(units, PROBES, DELIVERIES) == frozenset({"disclosure"})
    assert conducted_plugins([_unit("p-static"), _unit("p-control")], PROBES, DELIVERIES) == (
        frozenset()
    )


def test_delivery_provenance_counts_replayed_conversations_beside_this_attempt_s() -> None:
    """An attempt that saved a conducted trace and died before the dataset left no other record of
    it; counted from this attempt's door alone, the relaunch would report zero conversations and
    hide the one that ended early."""
    from redteam_contracts.trace import TraceLabels

    replayed = [
        TraceLabels(orchestration_technique=MANY_TURNS, ended=ENDED_BY_ATTACKER_FAILURE),
        TraceLabels(orchestration_technique=MANY_TURNS, ended=ENDED_BY_BOUND),
        TraceLabels(orchestration_technique=STATIC_TECHNIQUE),
        TraceLabels(orchestration_technique=MANY_TURNS, ended=ENDED_BY_ATTACKER),
    ]

    assert delivery_provenance(replayed, conducted=1, ended_early=0) == {
        "delivery_conducted": "4",
        "delivery_ended_early": "1",
    }
    assert delivery_provenance([], conducted=0, ended_early=0) == {
        "delivery_conducted": "0",
        "delivery_ended_early": "0",
    }
