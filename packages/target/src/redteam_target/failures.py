"""Classify transport exceptions and preserve structured failures in TargetResponse.raw.

Adapters return failed responses rather than leaking transport exceptions. HTTP classification
uses named HTTPStatus values; failure_of and failed_response own the raw-record representation."""

from __future__ import annotations

import email.utils
import json
from collections.abc import Callable
from datetime import UTC, datetime
from http import HTTPStatus
from typing import Any

import httpx
from gaussia.schemas.roastme import TargetResponse

from redteam_contracts.failure import (
    CLIENT_ERROR,
    EMPTY_RESPONSE,
    MALFORMED_RESPONSE,
    NETWORK,
    RATE_LIMITED,
    SERVER_ERROR,
    TIMEOUT,
    UNAUTHORIZED,
    UNKNOWN,
    UPSTREAM_UNAVAILABLE,
    TransportFailure,
)

FAILURE_KEY = "failure"
"""Where the record sits in `TargetResponse.raw`."""

MESSAGE_CHARS = 200

Classifier = Callable[[BaseException], TransportFailure | None]
"""Recognises one family of errors, or answers None and lets the next classifier look."""

_CLASSIFIERS: dict[str, Classifier] = {}
"""Consulted in registration order, so a narrow classifier registered first wins over a broad one:
a timeout is a transport error too, and it has to be named before the transport classifier sees
it."""


def register_classifier(name: str, classifier: Classifier) -> None:
    """Add a classifier under a name. Re-registering the same one is a no-op; a different one under
    a known name is refused, because two answers to "what was this failure" make the record
    unanswerable."""
    existing = _CLASSIFIERS.get(name)
    if existing is not None:
        if existing is classifier:
            return
        raise ValueError(
            f"classifier {name!r} is already registered; exactly one per name, or two of them "
            f"could read one failure as two kinds"
        )
    _CLASSIFIERS[name] = classifier


def registered_classifiers() -> tuple[str, ...]:
    return tuple(_CLASSIFIERS)


def classify(error: BaseException) -> TransportFailure:
    """The record for an exception, by the first classifier that recognises it.

    Never refuses: an error nothing recognises is `UNKNOWN`, carrying the class name and the text,
    which is what the old `failure_reason` carried in its entirety and is still the least a reader
    needs.
    """
    for classifier in _CLASSIFIERS.values():
        found = classifier(error)
        if found is not None:
            return found
    return TransportFailure(
        kind=UNKNOWN,
        message=str(error)[:MESSAGE_CHARS] or type(error).__name__,
        error_type=type(error).__name__,
    )


def failed_response(
    failure: TransportFailure,
    *,
    session_id: str | None = None,
    raw: dict[str, Any] | None = None,
) -> TargetResponse:
    """A failed `TargetResponse` carrying the record.

    `failure_reason` gets the one-line summary, so anything that reads only the string -- a log,
    gaussia's own ungraded reason -- still says what kind of failure it was; `raw` gets the record,
    beside whatever the adapter already keeps there (a task id, a runtime status).
    """
    return TargetResponse(
        content="",
        failed=True,
        failure_reason=failure.summary(),
        session_id=session_id,
        raw={**(raw or {}), FAILURE_KEY: failure.model_dump(mode="json")},
    )


def failure_of(response: TargetResponse) -> TransportFailure | None:
    """The record a failed response carries, or one made from its reason when it carries none.

    None for a response that did not fail. A failed response with no record -- a test's stand-in,
    a response rebuilt from an older trace -- is read as `UNKNOWN` with its `failure_reason` as the
    message, so every failed exchange has a kind and the policy always has something to answer.
    """
    if not response.failed:
        return None
    recorded = (response.raw or {}).get(FAILURE_KEY)
    if isinstance(recorded, dict):
        return TransportFailure.model_validate(recorded)
    return TransportFailure(
        kind=UNKNOWN,
        message=(response.failure_reason or "the exchange failed")[:MESSAGE_CHARS],
        error_type="unrecorded",
    )


def raw_failure(failure: TransportFailure | None) -> dict[str, Any]:
    """The `raw` fragment that carries a record, for a response rebuilt from a stored trace."""
    if failure is None:
        return {}
    return {FAILURE_KEY: failure.model_dump(mode="json")}


def empty_response(what: str, *, error_type: str = "empty") -> TransportFailure:
    """The record for an answer that arrived and said nothing."""
    return TransportFailure(kind=EMPTY_RESPONSE, message=what, error_type=error_type)


# ---- the shipped classifiers ------------------------------------------------------------------

_KIND_BY_STATUS: dict[HTTPStatus, str] = {
    HTTPStatus.TOO_MANY_REQUESTS: RATE_LIMITED,
    HTTPStatus.UNAUTHORIZED: UNAUTHORIZED,
    HTTPStatus.FORBIDDEN: UNAUTHORIZED,
    HTTPStatus.BAD_GATEWAY: UPSTREAM_UNAVAILABLE,
    HTTPStatus.SERVICE_UNAVAILABLE: UPSTREAM_UNAVAILABLE,
    HTTPStatus.GATEWAY_TIMEOUT: UPSTREAM_UNAVAILABLE,
}
"""The statuses that carry a meaning of their own, by name. Everything else is its range."""


def _kind_of(response: httpx.Response) -> str:
    try:
        status = HTTPStatus(response.status_code)
    except ValueError:
        # A code outside the standard's table. The ranges still say which side failed.
        status = None
    if status is not None and status in _KIND_BY_STATUS:
        return _KIND_BY_STATUS[status]
    if response.is_server_error:
        return SERVER_ERROR
    if response.is_client_error:
        return CLIENT_ERROR
    return UNKNOWN


def _retry_after(response: httpx.Response) -> float | None:
    """`Retry-After` as seconds, whether it was written as a delay or as an HTTP date."""
    header = response.headers.get("retry-after")
    if not header:
        return None
    try:
        return max(float(header), 0.0)
    except ValueError:
        pass
    try:
        at = email.utils.parsedate_to_datetime(header)
    except (TypeError, ValueError):
        return None
    if at.tzinfo is None:
        at = at.replace(tzinfo=UTC)
    return max((at - datetime.now(UTC)).total_seconds(), 0.0)


def _message(response: httpx.Response) -> str:
    """What the target said about the error: the body's message when it carries one, the status
    phrase otherwise, the raw text as a last resort."""
    try:
        body = response.json()
    except Exception:
        body = None
    if isinstance(body, dict):
        for key in ("error", "message", "detail"):
            value = body.get(key)
            if isinstance(value, dict):
                value = value.get("message")
            if isinstance(value, str) and value.strip():
                return value.strip()[:MESSAGE_CHARS]
    try:
        phrase = HTTPStatus(response.status_code).phrase
    except ValueError:
        phrase = ""
    return phrase or response.text.strip()[:MESSAGE_CHARS] or "the target answered with an error"


def http_status(error: BaseException) -> TransportFailure | None:
    """An HTTP error status: the one family where the target said what it meant."""
    if not isinstance(error, httpx.HTTPStatusError):
        return None
    response = error.response
    return TransportFailure(
        kind=_kind_of(response),
        status=response.status_code,
        retry_after_seconds=_retry_after(response),
        message=_message(response),
        error_type=type(error).__name__,
    )


def timeout(error: BaseException) -> TransportFailure | None:
    if not isinstance(error, httpx.TimeoutException):
        return None
    return TransportFailure(
        kind=TIMEOUT,
        message=str(error)[:MESSAGE_CHARS] or "the target did not answer in time",
        error_type=type(error).__name__,
    )


def network(error: BaseException) -> TransportFailure | None:
    """Registered after `timeout`, which is the narrower reading of the same family."""
    if not isinstance(error, httpx.TransportError):
        return None
    return TransportFailure(
        kind=NETWORK,
        message=str(error)[:MESSAGE_CHARS] or "the target could not be reached",
        error_type=type(error).__name__,
    )


def malformed(error: BaseException) -> TransportFailure | None:
    """An answer that could not be read as one: what raises between `response.json()` and the
    field the adapter reaches for."""
    if not isinstance(error, json.JSONDecodeError | KeyError | IndexError | TypeError | ValueError):
        return None
    return TransportFailure(
        kind=MALFORMED_RESPONSE,
        message=str(error)[:MESSAGE_CHARS] or "the answer could not be read",
        error_type=type(error).__name__,
    )


register_classifier("http_status", http_status)
register_classifier("timeout", timeout)
register_classifier("network", network)
register_classifier("malformed", malformed)
