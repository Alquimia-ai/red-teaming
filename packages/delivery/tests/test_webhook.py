"""Delivery: a bounded, deduplicable pointer into the store."""

from __future__ import annotations

from typing import Any

import httpx

from redteam_delivery import (
    ATTEMPTS,
    Delivered,
    NotAsked,
    Undelivered,
    deliver,
    idempotency_key,
)


class _Clock:
    def __init__(self) -> None:
        self.slept: list[float] = []

    def __call__(self, seconds: float) -> None:
        self.slept.append(seconds)


def _answers(*statuses: int) -> httpx.Client:
    """A receiver that answers each status in turn, then repeats the last."""
    answered: list[httpx.Request] = []
    remaining = list(statuses)

    def _handle(request: httpx.Request) -> httpx.Response:
        answered.append(request)
        status = remaining.pop(0) if len(remaining) > 1 else remaining[0]
        return httpx.Response(status)

    client = httpx.Client(transport=httpx.MockTransport(_handle))
    client.answered = answered  # type: ignore[attr-defined]
    return client


def test_a_run_that_declared_no_webhook_is_neither_delivered_nor_undelivered() -> None:
    answered = deliver(None, {"a": 1}, key="k")
    assert isinstance(answered, NotAsked)
    assert not isinstance(answered, Delivered | Undelivered)


def test_one_acknowledgement_is_the_whole_story() -> None:
    client = _answers(200)
    outcome = deliver("http://consumer/webhook", {"a": 1}, key="k", client=client)

    assert isinstance(outcome, Delivered)
    assert outcome.attempts == 1
    assert len(client.answered) == 1  # type: ignore[attr-defined]


def test_a_receiver_that_recovers_is_retried_until_it_does() -> None:
    """A restart or a proxy blip is the ordinary case, and it is the one the retries exist for."""
    clock = _Clock()
    client = _answers(503, 503, 200)

    outcome = deliver("http://consumer/webhook", {"a": 1}, key="k", sleep=clock, client=client)

    assert isinstance(outcome, Delivered)
    assert outcome.attempts == 3
    assert clock.slept == [2.0, 4.0], "backoff doubles: a tight loop against a struggling receiver"


def test_a_receiver_that_never_answers_is_reported_rather_than_retried_forever() -> None:
    clock = _Clock()
    client = _answers(500)

    outcome = deliver("http://consumer/webhook", {"a": 1}, key="k", sleep=clock, client=client)

    assert isinstance(outcome, Undelivered)
    assert outcome.attempts == ATTEMPTS
    assert "500" in outcome.why
    assert len(clock.slept) == ATTEMPTS - 1, "it sleeps between attempts, not after the last"


def test_a_transport_that_fails_is_the_same_kind_of_outcome_as_a_bad_status() -> None:
    def _refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("nothing is listening")

    outcome = deliver(
        "http://consumer/webhook",
        {"a": 1},
        key="k",
        attempts=2,
        sleep=lambda _: None,
        client=httpx.Client(transport=httpx.MockTransport(_refuse)),
    )

    assert isinstance(outcome, Undelivered)
    assert "ConnectError" in outcome.why


def test_delivery_never_raises_into_the_caller() -> None:
    """A caller in the middle of closing a run cannot be made to handle a transport error from the
    last thing it does: an exception here would turn a closed run into a failed attempt."""

    def _explode(request: httpx.Request) -> httpx.Response:
        raise RuntimeError("something nobody anticipated")

    outcome = deliver(
        "http://consumer/webhook",
        {"a": 1},
        key="k",
        attempts=1,
        client=httpx.Client(transport=httpx.MockTransport(_explode)),
    )

    assert isinstance(outcome, Undelivered)


def test_the_key_is_stable_across_retries_and_distinct_across_deliveries() -> None:
    assert idempotency_key("run-1", "complete") == idempotency_key("run-1", "complete")
    assert idempotency_key("run-1", "complete") != idempotency_key("run-1", "failed")
    assert idempotency_key("run-1", "complete") != idempotency_key("run-2", "complete")


def test_the_key_travels_on_every_attempt() -> None:
    clock = _Clock()
    client = _answers(503, 200)
    key = idempotency_key("run-1", "complete")

    deliver("http://consumer/webhook", {"a": 1}, key=key, sleep=clock, client=client)

    sent: list[Any] = client.answered  # type: ignore[attr-defined]
    assert [request.headers["Idempotency-Key"] for request in sent] == [key, key]
