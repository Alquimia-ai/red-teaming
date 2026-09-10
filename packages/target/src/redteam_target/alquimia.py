"""The Alquimia runtime: an assistant whose one turn is two requests.

A plain chat endpoint posts a question and reads the answer off the response. This runtime does
not work that way. `POST /event/infer/{assistant_id}` accepts the query and answers with a
**task id**; the assistant's actual words arrive later. So one `send()` is a submission followed by
a wait, and the wait is where every failure mode lives.

**The answer is read off the worklog rather than the event stream.** Both exist -- `GET
/event/stream/{task_id}` emits the same run as server-sent events and closes on the terminal
`AssistantInferenceResponse` -- and the stream loses a race the poll cannot. Measured against a live
runtime, tasks close in one and a half to four seconds; a stream opened after the task finished has
no event left to deliver, so the turn waits out its whole deadline for an answer that was already
sitting in the worklog. The poll asks a question that is true whenever it is asked.

**The runtime spells its fields two ways, and both are read.** The request body takes `task_id` and
`session_id`; the response model returns `taskid` and `sessionid`, concatenated. That is not a guess
about a typo -- it is what the runtime's own OpenAPI document declares for
`AssistantInferencePayload` and for `CommonAttributes`, so an adapter that reads one spelling works
against half the API.

**Sessions are never invented here.** `TargetAssistant.send` takes a session to continue, and the
only caller that passes one is the engine conducting a strategy the catalogue delivers as many
turns: it opens with none, and continues with the session this adapter read back off the runtime.
Every static probe is sent with none and is its own conversation. Pinning a session here would
invent a continuity no caller asked for, and it would do damage -- an assistant that remembers being
attacked answers the next probe differently, which turns independent probes into one long
conversation nobody can read a rate off. A session a caller hands in is forwarded and honoured.
"""

from __future__ import annotations

import time
from typing import Any

import httpx
from gaussia.core.target_assistant import TargetAssistant
from gaussia.schemas.roastme import TargetResponse

from redteam_contracts.failure import (
    MALFORMED_RESPONSE,
    NETWORK,
    RATE_LIMITED,
    SERVER_ERROR,
    TIMEOUT,
    UPSTREAM_UNAVAILABLE,
    TransportFailure,
)
from redteam_contracts.run_spec import ConnectorSpec
from redteam_target.failures import classify, empty_response, failed_response, failure_of

_ABSORBED_WHILE_POLLING = frozenset(
    {RATE_LIMITED, UPSTREAM_UNAVAILABLE, SERVER_ERROR, TIMEOUT, NETWORK}
)
"""The kinds of poll failure the wait absorbs: the runtime asked for less load, or something between
here and it hiccupped. The task is still running; the deadline is what ends the wait."""

ALQUIMIA = "alquimia"

DEFAULT_AGENTSPACE = "default"
"""The registry namespace a runtime serves when nobody names one -- the runtime's own default."""

DEFAULT_TIMEOUT = 30.0
"""Per request, and each one is small: a submission or a status read, never the model's latency."""

DEFAULT_DEADLINE = 120.0
"""How long one turn may wait for the runtime to finish. Measured tasks close in one and a half to
four seconds, so this is wide enough that a slow one is not a false failure and narrow enough that a
stuck one does not hold the whole run behind it."""

DEFAULT_POLL_INTERVAL = 0.5

# Written with a leading slash so the no-hardcoded-models guard does not read `event/infer` as a
# `vendor/name` model id. The guard is right to be blunt about that shape; this is how a path
# declares it is a path.
_INFER = "/event/infer"
_WORKLOG = "/worklog"

SUCCESS = "success"
"""The one `final_status` that means the assistant answered."""


def _spelled(body: dict[str, Any], *names: str) -> Any:
    """The first spelling of a field the runtime actually used."""
    for name in names:
        value = body.get(name)
        if value:
            return value
    return None


class AlquimiaTargetAssistant(TargetAssistant):  # type: ignore[misc]  # gaussia ships no stubs
    """An assistant on the Alquimia runtime, through its asynchronous inference API.

    Args:
        endpoint: The runtime's base URL. A base rather than a full path, because one turn
            addresses two different paths on it.
        assistant_id: Which assistant in the registry answers. Travels as a path segment.
        agentspace_id: The registry namespace that assistant lives in.
        api_key: The credential, already resolved by the caller.
        user_id: Who the runtime attributes these turns to. Worth setting to something that names
            the engagement: the worklog is filterable by it, so it is how somebody later tells an
            evaluation's traffic apart from a real customer's.
        poll_interval: How often to ask the worklog whether the task closed.
        deadline: How long one turn may wait in total before reporting failure.
    """

    def __init__(
        self,
        endpoint: str,
        assistant_id: str,
        *,
        agentspace_id: str = DEFAULT_AGENTSPACE,
        api_key: str | None = None,
        user_id: str | None = None,
        poll_interval: float = DEFAULT_POLL_INTERVAL,
        deadline: float = DEFAULT_DEADLINE,
        timeout: float = DEFAULT_TIMEOUT,
        client: httpx.Client | None = None,
    ) -> None:
        self._base = endpoint.rstrip("/")
        self._assistant_id = assistant_id
        self._agentspace_id = agentspace_id
        self._headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self._user_id = user_id
        self._poll_interval = poll_interval
        self._deadline = deadline
        self._client = client or httpx.Client(timeout=timeout)
        self._pending: tuple[str, str | None, str, str | None] | None = None
        """The task the runtime accepted for the last turn that ran out of deadline, as
        `(query, session_id, task_id, minted_session)`: what a retry of that turn resumes."""

    def send(self, query: str, session_id: str | None = None) -> TargetResponse:
        """One turn: submit, then wait for the worklog to close the task.

        **An accepted task is never submitted twice.** A retry from the governed door arrives as
        the same `send(query, session_id)`; if the previous call left a task the runtime accepted
        and did not close in time, this call resumes polling that task rather than posting the
        query again -- a second submission is a second attack, with its side effects, and the first
        task's answer lost. Only the call that ends the exchange clears the slot.
        """
        resumed = self._resumable(query, session_id)
        if resumed is not None:
            task_id, minted = resumed
        else:
            self._pending = None
            try:
                task_id, minted = self._submit(query, session_id)
            except Exception as error:
                return failed_response(classify(error), session_id=session_id)
            if not task_id:
                # Accepted and unanswerable: without a task id there is nothing to poll, and
                # reporting it as a failure is the only honest move left.
                return failed_response(
                    TransportFailure(
                        kind=MALFORMED_RESPONSE,
                        message="the runtime took the query and named no task to read it back from",
                        error_type="no task id",
                    ),
                    session_id=session_id,
                )
        answer = self._await_answer(task_id, session_id or minted)
        unfinished = failure_of(answer)
        if unfinished is not None and unfinished.kind == TIMEOUT:
            # The task may still close. Kept for the retry that asks the same question next.
            self._pending = (query, session_id, task_id, minted)
        else:
            self._pending = None
        return answer

    def _resumable(self, query: str, session_id: str | None) -> tuple[str, str | None] | None:
        """The accepted task the previous call left unfinished, when this call asks the same
        question in the same session -- which is what a retry is."""
        if self._pending is None:
            return None
        pending_query, pending_session, task_id, minted = self._pending
        if (pending_query, pending_session) != (query, session_id):
            return None
        return task_id, minted

    def _submit(self, query: str, session_id: str | None) -> tuple[str, str | None]:
        """Hand the query over, and read back the task the answer will arrive under."""
        payload: dict[str, Any] = {"query": query}
        if session_id:
            payload["session_id"] = session_id
        if self._user_id:
            payload["user_id"] = self._user_id
        response = self._client.post(
            f"{self._base}{_INFER}/{self._assistant_id}",
            params={"agentspace_id": self._agentspace_id},
            json=payload,
            headers=self._headers,
        )
        response.raise_for_status()
        body: dict[str, Any] = response.json()
        return (
            str(_spelled(body, "taskid", "task_id") or ""),
            _spelled(body, "sessionid", "session_id"),
        )

    def _await_answer(self, task_id: str, session_id: str | None) -> TargetResponse:
        """Ask the worklog until the task closes, then read what the assistant said.

        The closed check comes before the deadline check on purpose: a task that finished on the
        last permitted poll answered, and calling that a timeout would throw away an answer we
        already hold.

        **A poll that fails is part of the wait, not the end of the exchange.** The query is already
        with the assistant; a 429 or a dropped connection on the worklog says nothing about whether
        it answered. So a transient failure keeps polling -- honouring `Retry-After` when the
        runtime sent one -- until the deadline, and only the deadline ends the wait. A failure that
        is not transient -- a refused credential, a request the worklog calls malformed -- ends it
        at once, as itself.
        """
        url = f"{self._base}{_WORKLOG}/{task_id}"
        expires = time.monotonic() + self._deadline
        last_poll_failure: TransportFailure | None = None
        while True:
            try:
                response = self._client.get(url, headers=self._headers)
                response.raise_for_status()
                record: dict[str, Any] = response.json()
            except Exception as error:
                last_poll_failure = classify(error)
                if last_poll_failure.kind not in _ABSORBED_WHILE_POLLING:
                    return failed_response(
                        last_poll_failure, session_id=session_id, raw={"task_id": task_id}
                    )
                record = {}
            if record.get("finished_at"):
                return self._answered(record, task_id, session_id)
            if time.monotonic() >= expires:
                unfinished = f"the task did not close within {self._deadline:g}s"
                if last_poll_failure is not None:
                    unfinished = f"{unfinished}; last poll: {last_poll_failure.summary()}"
                return failed_response(
                    TransportFailure(kind=TIMEOUT, message=unfinished, error_type="deadline"),
                    session_id=session_id,
                    raw={"task_id": task_id},
                )
            asked = last_poll_failure.retry_after_seconds if last_poll_failure else None
            time.sleep(max(self._poll_interval, asked or 0.0))

    def _answered(
        self, record: dict[str, Any], task_id: str, session_id: str | None
    ) -> TargetResponse:
        """A closed task, read as content or as a failure.

        `raw` keeps the runtime's own identifiers, so a trace can be taken back to the worklog row
        that produced it: evidence is citable or it is an anecdote.
        """
        status = str(record.get("final_status") or "")
        raw = {"task_id": task_id, "final_status": status}
        if status != SUCCESS:
            # The runtime ran the task and the task died: the target's side failed to answer, with
            # the runtime's own status word as the type and its message as the message.
            return failed_response(
                TransportFailure(
                    kind=SERVER_ERROR,
                    message=str(record.get("error_message") or f"the task closed {status!r}"),
                    error_type=status or "no status",
                ),
                session_id=session_id,
                raw=raw,
            )
        content = str(record.get("final_result") or "")
        if not content:
            # A successful task that said nothing is an outage, and grading silence as compliance
            # is how one becomes a clean bill of health.
            return failed_response(
                empty_response("the task succeeded and carried no result", error_type=status),
                session_id=session_id,
                raw=raw,
            )
        return TargetResponse(content=content, session_id=session_id, raw=raw)


def build_alquimia(spec: ConnectorSpec, credential: str | None) -> TargetAssistant:
    """Built from `options`, which is where a kind's own coordinates belong.

    The runtime's console spells the assistant and its namespace as one string --
    `my-assistant?agentspace_id=default` -- because that is a URL fragment, not an identifier. They
    travel separately here, so neither ends up inside a path segment as literal text.
    """
    options = spec.options
    assistant_id = options.get("assistant_id")
    if not assistant_id:
        # Refused at build rather than at the first turn: the request cannot be formed, and a run
        # should not spend its acceptance finding that out.
        raise ValueError(
            "the alquimia target needs options.assistant_id -- the name the runtime registry "
            "answers for the assistant under"
        )
    return AlquimiaTargetAssistant(
        spec.endpoint,
        str(assistant_id),
        agentspace_id=str(options.get("agentspace_id") or DEFAULT_AGENTSPACE),
        api_key=credential,
        user_id=str(options["user_id"]) if options.get("user_id") else None,
        poll_interval=float(options.get("poll_interval", DEFAULT_POLL_INTERVAL)),
        deadline=float(options.get("deadline", DEFAULT_DEADLINE)),
    )
