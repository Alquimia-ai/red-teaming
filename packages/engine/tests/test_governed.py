"""The one door to the target: budget, pacing, and what happens to a failed exchange behind it.

These tests drive the whole path -- an adapter answering a real status, the classifier, the policy,
the gate -- and count what the assistant's infrastructure actually took.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from http import HTTPStatus
from typing import Any

import httpx
import pytest
from gaussia.schemas.roastme import TargetResponse

from redteam_engine.errors import TargetUnauthorized
from redteam_engine.governed import Budget, BudgetExhausted, GovernedTarget, RateGate
from redteam_target.capabilities import CapabilityGate
from redteam_target.failures import classify, failed_response


class _Scripted:
    """A target answering, in order, whatever it was scripted with; the last answer repeats."""

    def __init__(self, *answers: TargetResponse) -> None:
        self._answers: Iterator[TargetResponse] = iter(answers)
        self._last = answers[-1]
        self.calls = 0

    def send(self, query: str, session_id: str | None = None) -> TargetResponse:
        self.calls += 1
        return next(self._answers, self._last)


def _status(status: HTTPStatus, **headers: str) -> TargetResponse:
    """What an adapter reports for a target answering `status`: the real classifier over a real
    response, so the record carries the status by name and the `Retry-After` it sent."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, headers=headers)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    try:
        client.post("http://t").raise_for_status()
    except httpx.HTTPStatusError as error:
        return failed_response(classify(error))
    raise AssertionError("the scripted status did not raise")


OK = TargetResponse(content="an answer")


def _governed(
    target: Any, *, max_retries: int = 3, budget: Budget | None = None
) -> tuple[GovernedTarget, list[float], list[tuple[str, TargetResponse]]]:
    slept: list[float] = []
    recorded: list[tuple[str, TargetResponse]] = []
    door = GovernedTarget(
        target,
        gate=CapabilityGate(declared_capabilities=(), safe_mode=True),
        budget=budget or Budget(),
        rate=RateGate(sleep=slept.append),
        on_exchange=lambda query, response, conversation: recorded.append((query, response)),
        max_retries=max_retries,
    )
    return door, slept, recorded


def test_a_rate_limit_is_backed_off_as_the_target_asked_and_the_probe_is_sent_again() -> None:
    """One probe, two calls, one exchange: the Profiler sees one answer, the recorder sees one, the
    budget is charged twice, and the wait is the target's number."""
    target = _Scripted(_status(HTTPStatus.TOO_MANY_REQUESTS, **{"Retry-After": "7"}), OK)
    door, slept, recorded = _governed(target)

    response = door.send("q")

    assert response.content == "an answer"
    assert target.calls == 2
    assert slept == [7.0]
    assert door._budget.calls == 2
    assert [r.content for _, r in recorded] == ["an answer"]
    assert door.ledger.recovered == 1 and door.ledger.failed == []


def test_without_a_retry_after_the_backoff_is_exponential_and_capped() -> None:
    slept: list[float] = []
    gate = RateGate(sleep=slept.append, max_backoff_seconds=3.0)

    gate.back_off()
    gate.back_off()
    gate.back_off()
    gate.back_off(retry_after=60.0)

    assert slept == [2.0, 3.0, 3.0, 3.0], "2^1, then 2^2 and 2^3 capped, then a request capped"


def test_a_failure_without_a_retry_after_backs_off_exponentially_through_the_door() -> None:
    target = _Scripted(_status(HTTPStatus.SERVICE_UNAVAILABLE), OK)
    door, slept, _ = _governed(target)

    assert door.send("q").content == "an answer"
    assert slept == [2.0]


def test_retries_are_bounded_and_the_unit_is_then_given_up_on() -> None:
    target = _Scripted(_status(HTTPStatus.TOO_MANY_REQUESTS, **{"Retry-After": "1"}))
    door, slept, recorded = _governed(target, max_retries=2)

    response = door.send("q")

    assert response.failed
    assert target.calls == 3, "one attempt and two retries"
    assert slept == [1.0, 1.0]
    assert len(recorded) == 1, "the recorder sees the final answer, once"
    assert [f.kind for f in door.ledger.failed] == ["rate_limited"]


def test_zero_retries_is_one_attempt() -> None:
    target = _Scripted(_status(HTTPStatus.TOO_MANY_REQUESTS), OK)
    door, slept, _ = _governed(target, max_retries=0)

    assert door.send("q").failed
    assert target.calls == 1 and slept == []


def test_a_refused_credential_aborts_the_run_after_recording_the_exchange() -> None:
    """Every further call would be a wasted attack on the assistant. The exchange is recorded
    first: the store is the evidence, and a run that died of a 401 has to show the 401."""
    target = _Scripted(_status(HTTPStatus.UNAUTHORIZED), OK)
    door, slept, recorded = _governed(target)

    with pytest.raises(TargetUnauthorized) as died:
        door.send("q")

    assert target.calls == 1 and slept == []
    assert len(recorded) == 1 and recorded[0][1].failed
    assert died.value.kind == "unauthorized"
    assert died.value.failure.status == HTTPStatus.UNAUTHORIZED


def test_a_failure_repeating_the_request_would_not_change_is_not_retried() -> None:
    target = _Scripted(_status(HTTPStatus.IM_A_TEAPOT), OK)
    door, slept, _ = _governed(target)

    assert door.send("q").failed
    assert target.calls == 1 and slept == []
    assert [f.kind for f in door.ledger.failed] == ["client_error"]


def test_a_failed_answer_with_no_record_is_given_up_on_rather_than_guessed_about() -> None:
    """A stand-in target, or a response rebuilt from an older trace."""
    target = _Scripted(TargetResponse(content="", failed=True, failure_reason="broke"), OK)
    door, _, _ = _governed(target)

    assert door.send("q").failed
    assert target.calls == 1
    assert [f.kind for f in door.ledger.failed] == ["unknown"]


def test_a_success_resets_the_backoff() -> None:
    target = _Scripted(
        _status(HTTPStatus.SERVICE_UNAVAILABLE), OK, _status(HTTPStatus.SERVICE_UNAVAILABLE), OK
    )
    door, slept, _ = _governed(target)

    door.send("q")
    door.send("q")

    assert slept == [2.0, 2.0], "the second failure starts the exponential over"


def test_the_wall_clock_budget_stops_the_run() -> None:
    budget = Budget(max_wall_seconds=1)
    budget.started_at = time.monotonic() - 5
    door, _, _ = _governed(_Scripted(OK), budget=budget)

    with pytest.raises(BudgetExhausted, match="wall-clock"):
        door.send("q")


def test_a_budget_that_runs_out_before_the_retry_still_records_the_failure_that_happened() -> None:
    """One call was made and it failed; the retry never got its chance. Left unrecorded, the unit
    would read as never touched rather than as failed -- no marker, no evidence, nothing for the
    ledger."""
    target = _Scripted(_status(HTTPStatus.TOO_MANY_REQUESTS, **{"Retry-After": "0"}), OK)
    door, slept, recorded = _governed(target, budget=Budget(max_target_calls=1))

    with pytest.raises(BudgetExhausted):
        door.send("q")

    assert target.calls == 1
    assert slept == [0.0], "the back-off happened; the second charge is what refused"
    assert len(recorded) == 1 and recorded[0][1].failed, (
        "the one exchange that happened is recorded"
    )
    assert [f.kind for f in door.ledger.failed] == ["rate_limited"]


def test_every_retry_is_charged_to_the_call_budget() -> None:
    """The ceiling is on what the assistant's infrastructure takes, not on what the plan
    intended."""
    target = _Scripted(_status(HTTPStatus.TOO_MANY_REQUESTS, **{"Retry-After": "0"}))
    door, _, _ = _governed(target, budget=Budget(max_target_calls=2), max_retries=5)

    with pytest.raises(BudgetExhausted):
        door.send("q")
    assert target.calls == 2


def test_the_safe_mode_gate_refuses_before_the_first_turn() -> None:
    from redteam_target.capabilities import SafeModeViolation

    with pytest.raises(SafeModeViolation):
        GovernedTarget(
            _Scripted(OK),
            gate=CapabilityGate(declared_capabilities=("transfer_money",), safe_mode=False),
            budget=Budget(),
        )


def test_a_classified_failure_from_any_exception_reaches_the_policy() -> None:
    """The record, not the class name, is what the door reads -- so a stand-in target can hand it
    a classified failure directly and the same policy applies."""
    request = httpx.Request("POST", "http://t")
    error = httpx.HTTPStatusError(
        "boom",
        request=request,
        response=httpx.Response(HTTPStatus.BAD_GATEWAY, request=request),
    )
    target = _Scripted(failed_response(classify(error)), OK)
    door, slept, _ = _governed(target)

    assert door.send("q").content == "an answer"
    assert slept == [2.0]
