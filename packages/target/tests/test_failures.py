"""What an adapter reports when the channel fails: a record with a kind, never a class name."""

from __future__ import annotations

from http import HTTPStatus

import httpx
import pytest
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
from redteam_target import failures
from redteam_target.failures import (
    classify,
    empty_response,
    failed_response,
    failure_of,
    register_classifier,
)


def _answering(
    status: int, *, headers: dict[str, str] | None = None, **body: object
) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        if body:
            return httpx.Response(status, headers=headers, json=body)
        return httpx.Response(status, headers=headers)

    return httpx.Client(transport=httpx.MockTransport(handler))


def _raising(error: type[httpx.TransportError]) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        raise error("the wire", request=request)

    return httpx.Client(transport=httpx.MockTransport(handler))


def _failure(client: httpx.Client) -> TransportFailure:
    """What an adapter does around a request: raise for status, read the body, reach for a field,
    and classify whatever came out of that."""
    try:
        response = client.post("http://t", json={"message": "hi"})
        response.raise_for_status()
        content = str(response.json().get("reply", ""))
    except Exception as error:
        return classify(error)
    if not content:
        return empty_response("empty response body")
    raise AssertionError("the target answered; nothing to classify")


def test_a_rate_limit_is_read_as_one_with_what_the_target_asked_for() -> None:
    """The failure a class name would report as `HTTPStatusError`, indistinguishable from a 500,
    and the one the rate gate exists for."""
    failure = _failure(
        _answering(
            HTTPStatus.TOO_MANY_REQUESTS,
            headers={"Retry-After": "7"},
            error={"message": "Rate limit exceeded", "type": "rate_limit_error"},
        )
    )

    assert failure.kind == RATE_LIMITED
    assert failure.status == HTTPStatus.TOO_MANY_REQUESTS
    assert failure.retry_after_seconds == 7
    assert failure.message == "Rate limit exceeded"
    assert failure.error_type == "HTTPStatusError"
    assert failure.summary() == "rate_limited: HTTP 429 Rate limit exceeded, retry after 7s"


@pytest.mark.parametrize(
    ("status", "kind"),
    [
        (HTTPStatus.UNAUTHORIZED, UNAUTHORIZED),
        (HTTPStatus.FORBIDDEN, UNAUTHORIZED),
        (HTTPStatus.BAD_GATEWAY, UPSTREAM_UNAVAILABLE),
        (HTTPStatus.SERVICE_UNAVAILABLE, UPSTREAM_UNAVAILABLE),
        (HTTPStatus.GATEWAY_TIMEOUT, UPSTREAM_UNAVAILABLE),
        (HTTPStatus.INTERNAL_SERVER_ERROR, SERVER_ERROR),
        (HTTPStatus.NOT_IMPLEMENTED, SERVER_ERROR),
        (HTTPStatus.IM_A_TEAPOT, CLIENT_ERROR),
        (HTTPStatus.NOT_FOUND, CLIENT_ERROR),
    ],
)
def test_a_status_is_classified_by_name_then_by_range(status: HTTPStatus, kind: str) -> None:
    failure = _failure(_answering(status))
    assert failure.kind == kind
    assert failure.status == status
    assert failure.message == status.phrase, "no body, so the phrase is what the target said"


def test_a_status_outside_the_standard_table_is_still_classified_by_range() -> None:
    assert _failure(_answering(599)).kind == SERVER_ERROR
    assert _failure(_answering(499)).kind == CLIENT_ERROR


def test_retry_after_written_as_a_date_is_read_as_seconds_from_now() -> None:
    failure = _failure(
        _answering(
            HTTPStatus.TOO_MANY_REQUESTS,
            headers={"Retry-After": "Wed, 21 Oct 2015 07:28:00 GMT"},
        )
    )
    assert failure.retry_after_seconds == 0.0, "a date in the past is 'now', never negative"


def test_a_timeout_and_a_connection_error_are_the_channel_not_the_target() -> None:
    assert _failure(_raising(httpx.ReadTimeout)).kind == TIMEOUT
    assert _failure(_raising(httpx.ConnectError)).kind == NETWORK
    assert _failure(_raising(httpx.ConnectError)).error_type == "ConnectError"


def test_an_answer_that_cannot_be_read_is_malformed_and_an_empty_one_is_empty() -> None:
    def not_json(request: httpx.Request) -> httpx.Response:
        return httpx.Response(HTTPStatus.OK, text="<html>bad gateway</html>")

    malformed = _failure(httpx.Client(transport=httpx.MockTransport(not_json)))
    assert malformed.kind == MALFORMED_RESPONSE
    assert malformed.error_type == "JSONDecodeError"

    empty = _failure(_answering(HTTPStatus.OK, reply=""))
    assert empty.kind == EMPTY_RESPONSE


def test_a_shape_the_adapter_could_not_read_is_malformed_with_what_raised() -> None:
    """What raises between `response.json()` and the field the adapter reaches for."""
    found = classify(IndexError("list index out of range"))
    assert found.kind == MALFORMED_RESPONSE
    assert found.error_type == "IndexError"
    assert classify(KeyError("choices")).kind == MALFORMED_RESPONSE


def test_the_record_travels_in_raw_and_the_reason_is_its_summary() -> None:
    """gaussia reads `failed` and `failure_reason`; the record rides in `raw`, which gaussia
    declares for exactly this. Nothing is forked."""
    failure = TransportFailure(kind=RATE_LIMITED, message="slow down", error_type="X", status=429)
    response = failed_response(failure, session_id="s", raw={"task_id": "t"})

    assert response.failed and response.content == ""
    assert response.failure_reason == failure.summary()
    assert response.session_id == "s"
    assert response.raw["task_id"] == "t", "what the adapter already kept in raw is kept"
    assert failure_of(response) == failure


def test_a_failed_response_with_no_record_is_read_as_unknown_with_its_reason() -> None:
    """A test's stand-in, or a response rebuilt from an older trace: still a kind, so the policy
    always has something to answer."""
    legacy = TargetResponse(content="", failed=True, failure_reason="503")
    found = failure_of(legacy)
    assert found is not None
    assert found.kind == UNKNOWN
    assert found.message == "503"
    assert failure_of(TargetResponse(content="fine")) is None


def test_an_exception_nothing_recognises_is_unknown_with_its_class_name() -> None:
    class Peculiar(Exception):
        pass

    found = classify(Peculiar("something odd"))
    assert found.kind == UNKNOWN
    assert found.error_type == "Peculiar"
    assert found.message == "something odd"


def test_a_second_classifier_under_one_name_is_refused_and_the_same_one_is_a_no_op() -> None:
    def mine(error: BaseException) -> TransportFailure | None:
        return None

    def other(error: BaseException) -> TransportFailure | None:
        return None

    register_classifier("test-only", mine)
    register_classifier("test-only", mine)
    with pytest.raises(ValueError, match="exactly one per name"):
        register_classifier("test-only", other)
    assert "test-only" in failures.registered_classifiers()


def test_the_timeout_classifier_runs_before_the_transport_one() -> None:
    """A timeout is a transport error too; registration order is what names it correctly."""
    names = failures.registered_classifiers()
    assert names.index("timeout") < names.index("network")
