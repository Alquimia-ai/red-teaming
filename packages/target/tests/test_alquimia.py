"""The Alquimia adapter: one turn is a submission and a wait, and the wait can fail six ways.

Every test here drives the real two-request shape through `httpx.MockTransport`, because that is
the seam the adapter takes a client on. What is being pinned is not "it can parse JSON" -- it is
that a runtime which answers with a task id instead of an answer never turns into a raised
exception, a hang, or an empty string that reads as a compliant silence.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from redteam_contracts.failure import SERVER_ERROR, UPSTREAM_UNAVAILABLE
from redteam_contracts.run_spec import ConnectorSpec
from redteam_target import KINDS, UnknownTarget, build_target
from redteam_target.alquimia import ALQUIMIA, AlquimiaTargetAssistant
from redteam_target.failures import failure_of

BASE = "http://runtime.test"
ANSWER = "Estas son las principales lineas de seguros."
TASK = "task-abc123"
MINTED_SESSION = "session-minted-by-the-runtime"


class _Runtime:
    """A stand-in for the runtime: accepts an inference, then closes the task after `closes_after`
    polls. Records every request so a test can assert on the wire rather than on the return."""

    def __init__(
        self,
        *,
        closes_after: int = 1,
        final_status: str = "success",
        final_result: str | None = ANSWER,
        error_message: str | None = None,
        task_field: str = "taskid",
        infer_status: int = 200,
        worklog_status: int = 200,
    ) -> None:
        self.closes_after = closes_after
        self.final_status = final_status
        self.final_result = final_result
        self.error_message = error_message
        self.task_field = task_field
        self.infer_status = infer_status
        self.worklog_status = worklog_status
        self.requests: list[httpx.Request] = []
        self.polls = 0

    def client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self._handle))

    @property
    def submitted(self) -> dict[str, Any]:
        import json

        return dict(json.loads(self.requests[0].content))

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if "/event/infer" in request.url.path:
            if self.infer_status != 200:
                return httpx.Response(self.infer_status)
            return httpx.Response(200, json={self.task_field: TASK, "sessionid": MINTED_SESSION})
        if self.worklog_status != 200:
            return httpx.Response(self.worklog_status)
        self.polls += 1
        if self.polls < self.closes_after:
            return httpx.Response(200, json={"task_id": TASK, "finished_at": None})
        record: dict[str, Any] = {
            "task_id": TASK,
            "final_status": self.final_status,
            "final_result": self.final_result,
            "error_message": self.error_message,
            "finished_at": "2026-09-04T09:00:00Z",
        }
        return httpx.Response(200, json=record)


def _adapter(runtime: _Runtime, **kwargs: Any) -> AlquimiaTargetAssistant:
    kwargs.setdefault("poll_interval", 0.0)
    return AlquimiaTargetAssistant(
        BASE, "the-assistant", api_key="the-key", client=runtime.client(), **kwargs
    )


def test_the_answer_comes_from_the_worklog_not_from_the_submission() -> None:
    """The submission answers with a task id and no content. An adapter that read the answer off
    that response would grade every turn as an outage."""
    runtime = _Runtime()

    response = _adapter(runtime).send("what do you cover?")

    assert response.content == ANSWER
    assert not response.failed
    paths = [str(request.url.path) for request in runtime.requests]
    assert paths == ["/event/infer/the-assistant", f"/worklog/{TASK}"]


def test_the_credential_reaches_both_requests_as_a_bearer_token() -> None:
    """The worklog is authenticated too. A credential sent only on the submission reads the answer
    back as a 401, which would surface as a transport failure on every single turn."""
    runtime = _Runtime()

    _adapter(runtime).send("hi")

    assert [r.headers.get("authorization") for r in runtime.requests] == [
        "Bearer the-key",
        "Bearer the-key",
    ]


def test_the_assistant_travels_in_the_path_and_the_namespace_in_the_query() -> None:
    """The runtime's console spells these as one string, `id?agentspace_id=default`. Sent that way
    the id would be URL-encoded into a path segment and address nothing."""
    runtime = _Runtime()

    AlquimiaTargetAssistant(
        BASE,
        "pre-sales-assistant",
        agentspace_id="a-namespace",
        client=runtime.client(),
        poll_interval=0.0,
    ).send("hi")

    submission = runtime.requests[0]
    assert submission.url.path == "/event/infer/pre-sales-assistant"
    assert submission.url.params["agentspace_id"] == "a-namespace"


def test_the_default_namespace_is_the_runtimes_own() -> None:
    runtime = _Runtime()
    AlquimiaTargetAssistant(BASE, "a", client=runtime.client(), poll_interval=0.0).send("hi")
    assert runtime.requests[0].url.params["agentspace_id"] == "default"


def test_a_task_that_closes_late_is_waited_for() -> None:
    """The first poll can legitimately find the task still open."""
    runtime = _Runtime(closes_after=3)

    response = _adapter(runtime).send("hi")

    assert response.content == ANSWER
    assert runtime.polls == 3


def test_both_spellings_of_the_task_id_are_read() -> None:
    """The response model returns `taskid`; the request body takes `task_id`. Reading one spelling
    works against half the API, and which half is not documented anywhere but the schema."""
    for field in ("taskid", "task_id"):
        response = _adapter(_Runtime(task_field=field)).send("hi")
        assert response.content == ANSWER, f"the {field!r} spelling was not read"


def test_a_submission_that_fails_is_reported_and_never_raised() -> None:
    """If it raises, the run dies. The obligation the interface cannot express."""
    response = _adapter(_Runtime(infer_status=503)).send("hi")

    assert response.failed
    assert response.content == ""
    failure = failure_of(response)
    assert failure is not None
    assert failure.kind == UPSTREAM_UNAVAILABLE and failure.error_type == "HTTPStatusError"


def test_a_worklog_that_stays_unreadable_is_a_timeout_naming_the_task_and_the_last_poll() -> None:
    """The query was already spent against the client's assistant, so the task id is the one thing
    worth keeping: it is what makes the exchange findable afterwards. A worklog answering 500 is
    part of the wait, not the end of it; only the deadline ends the wait, and it says what the last
    poll answered."""
    response = _adapter(_Runtime(worklog_status=500), deadline=0.0).send("hi")

    assert response.failed
    assert response.raw["task_id"] == TASK
    failure = failure_of(response)
    assert failure is not None and failure.kind == "timeout"
    assert "last poll: server_error: HTTP 500" in failure.message


def test_a_transient_poll_failure_keeps_polling_the_same_task_rather_than_resubmitting() -> None:
    """The query is already with the assistant; a 429 on the worklog says nothing about whether it
    answered. A retry that re-posted the query was a second attack, with the first answer lost."""

    class _RateLimitedOnce(_Runtime):
        def __init__(self) -> None:
            super().__init__(closes_after=1)
            self._limited = False

        def _handle(self, request: httpx.Request) -> httpx.Response:
            if "/worklog/" in request.url.path and not self._limited:
                self._limited = True
                self.requests.append(request)
                return httpx.Response(429, headers={"Retry-After": "0"})
            return super()._handle(request)

    runtime = _RateLimitedOnce()

    response = _adapter(runtime).send("hi")

    assert response.content == ANSWER
    paths = [str(request.url.path) for request in runtime.requests]
    assert paths == ["/event/infer/the-assistant", f"/worklog/{TASK}", f"/worklog/{TASK}"]


def test_a_retry_after_the_deadline_resumes_the_accepted_task_instead_of_submitting_again() -> None:
    """What the governed door does on a timeout is call `send` again with the same query. The task
    the runtime accepted is still running; it is polled again, never posted again."""
    runtime = _Runtime(closes_after=10_000)
    adapter = _adapter(runtime, deadline=0.0)

    first = adapter.send("hi")
    runtime.closes_after = runtime.polls + 1
    second = adapter.send("hi")
    other = adapter.send("something else")

    assert first.failed and first.raw["task_id"] == TASK
    assert second.content == ANSWER
    submissions = [r for r in runtime.requests if "/event/infer" in r.url.path]
    assert len(submissions) == 2, "one for 'hi', resumed on retry; one for the other question"
    assert not other.failed or other.raw["task_id"] == TASK


def test_a_poll_failure_that_is_not_transient_ends_the_exchange_as_itself() -> None:
    """A refused credential on the worklog is not a hiccup to wait out."""
    response = _adapter(_Runtime(worklog_status=401), deadline=10.0).send("hi")

    failure = failure_of(response)
    assert failure is not None and failure.kind == "unauthorized"
    assert response.raw["task_id"] == TASK


def test_a_submission_that_names_no_task_is_a_failure() -> None:
    """Accepted and unanswerable. There is nothing to poll, so there is nothing to wait for."""
    runtime = _Runtime()
    runtime._handle = lambda request: httpx.Response(200, json={"sessionid": "s"})  # type: ignore[method-assign]

    response = _adapter(runtime).send("hi")

    assert response.failed
    assert "named no task" in str(response.failure_reason)


def test_a_task_that_failed_carries_the_runtimes_own_reason() -> None:
    """`error_message` is the runtime's account of what broke. Replacing it with ours sends whoever
    reads the trace after the wrong thing."""
    runtime = _Runtime(final_status="error", final_result=None, error_message="the model timed out")

    response = _adapter(runtime).send("hi")

    assert response.failed
    failure = failure_of(response)
    assert failure is not None
    assert failure.message == "the model timed out"
    assert failure.kind == SERVER_ERROR and failure.error_type == "error"
    assert response.failure_reason == "server_error: the model timed out"
    assert response.raw["final_status"] == "error"


def test_a_task_that_failed_without_a_reason_still_says_what_happened() -> None:
    runtime = _Runtime(final_status="cancelled", final_result=None)

    response = _adapter(runtime).send("hi")

    assert response.failed
    assert "cancelled" in str(response.failure_reason)


def test_a_successful_task_with_no_result_is_a_failure_not_a_silence() -> None:
    """An empty body is an outage. Grading it as compliance is how one becomes a clean bill of
    health."""
    response = _adapter(_Runtime(final_result="")).send("hi")

    assert response.failed
    assert response.content == ""
    assert "no result" in str(response.failure_reason)


def test_a_task_that_never_closes_fails_on_the_deadline_rather_than_hanging() -> None:
    """A turn that waits forever holds the whole run behind it, and the run has a budget in wall
    clock as well as in calls."""
    runtime = _Runtime(closes_after=10_000)

    response = _adapter(runtime, deadline=0.0).send("hi")

    assert response.failed
    assert "did not close" in str(response.failure_reason)
    assert runtime.polls == 1, "the deadline is checked after a poll, so one is always spent"


def test_a_session_the_caller_supplies_is_forwarded_and_kept() -> None:
    """The interface says a caller may thread a session, and an adapter that dropped it would
    silently answer a multi-turn probe with no context."""
    runtime = _Runtime()

    response = _adapter(runtime).send("hi", session_id="mine")

    assert runtime.submitted["session_id"] == "mine"
    assert response.session_id == "mine"


def test_a_turn_with_no_session_sends_none_and_returns_the_minted_one() -> None:
    """Every probe is its own conversation: nothing is pinned, and the runtime's own session id
    comes back so a caller that wants continuity can ask for it."""
    runtime = _Runtime()

    response = _adapter(runtime).send("hi")

    assert "session_id" not in runtime.submitted
    assert response.session_id == MINTED_SESSION


def test_a_user_id_is_sent_only_when_it_was_declared() -> None:
    """The worklog is filterable by it, which is how an evaluation's traffic is told apart from a
    real customer's later."""
    plain = _Runtime()
    _adapter(plain).send("hi")
    assert "user_id" not in plain.submitted

    named = _Runtime()
    _adapter(named, user_id="red-teaming-run").send("hi")
    assert named.submitted["user_id"] == "red-teaming-run"


# ---- building it from a spec ------------------------------------------------------------------


def _spec(**options: object) -> ConnectorSpec:
    return ConnectorSpec(kind=ALQUIMIA, endpoint=BASE, secret_ref="K", options=options)


def test_the_kind_is_one_of_the_two_shipped() -> None:
    assert ALQUIMIA in KINDS


def test_the_kind_builds_its_own_transport() -> None:
    assert isinstance(build_target(_spec(assistant_id="a"), "k"), AlquimiaTargetAssistant)


def test_the_adapter_needs_an_assistant_id_and_says_so_at_build() -> None:
    """The request cannot be formed without it, and a run should not spend its acceptance finding
    that out."""
    with pytest.raises(ValueError, match=r"options\.assistant_id"):
        build_target(_spec(), "k")


def test_a_typo_in_the_kind_is_refused_naming_the_kinds() -> None:
    with pytest.raises(UnknownTarget, match="alquimia, replay"):
        build_target(ConnectorSpec(kind="alquimia-runtime", endpoint=BASE, secret_ref="K"), None)
