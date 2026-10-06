"""A hosted judge must be ready before an attempt spends its conversations."""

from __future__ import annotations

import httpx
import pytest

from redteam_contracts.run_spec import ModelSpec
from redteam_runner.readiness import JudgeNotReady, wait_for_judge

JUDGE = ModelSpec(
    model="nemotron",
    provider="openai_compatible",
    endpoint="https://judge.example/v1",
)


def test_cold_start_waits_for_a_ready_judge() -> None:
    statuses = iter((503, 503, 200))
    requests: list[httpx.Request] = []

    def answer(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(next(statuses))

    ready = wait_for_judge(
        JUDGE,
        "declared-key",
        cancelled=lambda: False,
        interval_seconds=0,
        transport=httpx.MockTransport(answer),
    )

    assert ready
    assert len(requests) == 3
    assert {str(request.url) for request in requests} == {"https://judge.example/v1/models"}
    assert {request.headers["Authorization"] for request in requests} == {"Bearer declared-key"}


def test_a_judge_that_never_warms_up_fails_before_the_run() -> None:
    with pytest.raises(JudgeNotReady, match="HTTP 503"):
        wait_for_judge(
            JUDGE,
            "declared-key",
            cancelled=lambda: False,
            max_wait_seconds=0,
            transport=httpx.MockTransport(lambda _: httpx.Response(503)),
        )


def test_an_invalid_judge_credential_is_not_treated_as_warmup() -> None:
    with pytest.raises(JudgeNotReady, match="HTTP 401"):
        wait_for_judge(
            JUDGE,
            "wrong-key",
            cancelled=lambda: False,
            transport=httpx.MockTransport(lambda _: httpx.Response(401)),
        )


def test_cancellation_stops_waiting() -> None:
    called = False

    def answer(_: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(503)

    assert not wait_for_judge(
        JUDGE,
        "declared-key",
        cancelled=lambda: True,
        transport=httpx.MockTransport(answer),
    )
    assert not called


def test_a_stand_in_judge_does_not_probe_any_provider() -> None:
    assert wait_for_judge(
        ModelSpec(model="stand-in"),
        None,
        cancelled=lambda: False,
        transport=httpx.MockTransport(lambda _: pytest.fail("unexpected request")),
    )
