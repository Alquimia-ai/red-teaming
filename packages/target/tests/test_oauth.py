"""Exercise token renewal on the real connector without reaching a live assistant."""

import json
from http import HTTPStatus
from urllib.parse import parse_qs

import httpx
import pytest

from redteam_target.alquimia import AlquimiaTargetAssistant
from redteam_target.failures import failure_of
from redteam_target.oauth import target_auth

TOKEN_URL = "https://identity.test/token"
BASE = "http://runtime.test"
SECRET = json.dumps(
    {
        "type": "oauth2_client_credentials",
        "token_endpoint": TOKEN_URL,
        "client_id": "runner",
        "client_secret": "private-client-secret",
    }
)


def test_renewal_during_polling_never_resubmits(monkeypatch: pytest.MonkeyPatch) -> None:
    now = [0.0]
    monkeypatch.setattr("redteam_target.oauth.time.monotonic", lambda: now[0])
    tokens: list[str] = []
    submitted = []
    polled = []

    def handle(request: httpx.Request) -> httpx.Response:
        if str(request.url) == TOKEN_URL:
            assert "authorization" not in request.headers
            assert parse_qs(request.content.decode()) == {
                "grant_type": ["client_credentials"],
                "client_id": ["runner"],
                "client_secret": ["private-client-secret"],
            }
            tokens.append(f"access-{len(tokens)}")
            return httpx.Response(
                HTTPStatus.OK,
                json={"access_token": tokens[-1], "expires_in": 10, "token_type": "Bearer"},
            )
        if request.method == "POST":
            submitted.append(request)
            now[0] = 9.1
            return httpx.Response(HTTPStatus.OK, json={"taskid": "accepted"})
        polled.append(request)
        return httpx.Response(
            HTTPStatus.OK,
            json={"finished_at": "today", "final_status": "success", "final_result": "answer"},
        )

    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        target = AlquimiaTargetAssistant(BASE, "agent", api_key=SECRET, client=client)
        assert target.send("question").content == "answer"
    assert len(submitted) == len(polled) == 1
    assert tokens == ["access-0", "access-1"]
    assert submitted[0].headers["Authorization"] == "Bearer access-0"
    assert polled[0].headers["Authorization"] == "Bearer access-1"


def test_cache_and_unauthorized_invalidate_without_replaying() -> None:
    issued = []
    calls = []

    def handle(request: httpx.Request) -> httpx.Response:
        if str(request.url) == TOKEN_URL:
            issued.append(request)
            return httpx.Response(
                HTTPStatus.OK,
                json={"access_token": "access", "expires_in": 300, "token_type": "Bearer"},
            )
        calls.append(request)
        return httpx.Response(HTTPStatus.UNAUTHORIZED if len(calls) == 2 else HTTPStatus.OK)

    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        auth = target_auth(SECRET, BASE)
        for _ in range(3):
            client.get(BASE + "/worklog/", auth=auth)
    assert len(issued) == 2
    assert len(calls) == 3


@pytest.mark.parametrize("status", [HTTPStatus.UNAUTHORIZED, HTTPStatus.SERVICE_UNAVAILABLE])
def test_token_endpoint_errors_are_sanitized(status: HTTPStatus) -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == TOKEN_URL  # Never reaches inference after token failure.
        return httpx.Response(status, json={"error": "private-client-secret access-token"})

    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        response = AlquimiaTargetAssistant(BASE, "agent", api_key=SECRET, client=client).send("q")
    failure = failure_of(response)
    assert failure is not None
    assert failure.status == status
    assert "private-client-secret" not in str(response)
    assert "access-token" not in str(response)


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"access_token": "private", "expires_in": 0, "token_type": "Bearer"},
        {"access_token": "private", "expires_in": "nan", "token_type": "Bearer"},
        {"access_token": "private", "expires_in": 10, "token_type": "unknown"},
        {"access_token": "invalid token", "expires_in": 10, "token_type": "Bearer"},
    ],
)
def test_invalid_token_response_does_not_leak(body: dict[str, object]) -> None:
    with httpx.Client(
        transport=httpx.MockTransport(lambda _: httpx.Response(HTTPStatus.OK, json=body))
    ) as client:
        response = AlquimiaTargetAssistant(BASE, "agent", api_key=SECRET, client=client).send("q")
    assert response.failed
    assert "private" not in str(response)


@pytest.mark.parametrize("value", ["{broken", SECRET.replace("https://", "http://"), "{}"])
def test_invalid_secret_has_safe_error(value: str) -> None:
    with pytest.raises(ValueError, match=r"^invalid OAuth client-credentials secret$"):
        target_auth(value, BASE)


def test_origin_binding() -> None:
    with (
        httpx.Client(transport=httpx.MockTransport(lambda _: pytest.fail("unexpected HTTP"))) as c,
        pytest.raises(ValueError, match="origin mismatch"),
    ):
        c.get("https://other.test", auth=target_auth(SECRET, BASE))


def test_token_transport_failure_is_sanitized() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("private-client-secret in provider diagnostic", request=request)

    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        response = AlquimiaTargetAssistant(BASE, "agent", api_key=SECRET, client=client).send("q")
    assert response.failed
    assert "private-client-secret" not in str(response)


def test_forbidden_does_not_refresh_or_replay() -> None:
    requests = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if str(request.url) == TOKEN_URL:
            return httpx.Response(
                HTTPStatus.OK,
                json={"access_token": "access", "expires_in": 300, "token_type": "Bearer"},
            )
        return httpx.Response(HTTPStatus.FORBIDDEN)

    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        auth = target_auth(SECRET, BASE)
        client.get(BASE, auth=auth)
        client.get(BASE, auth=auth)
    assert len(requests) == 3


def test_expired_token_on_resumed_task_does_not_resubmit(monkeypatch: pytest.MonkeyPatch) -> None:
    now = [0.0]
    monkeypatch.setattr("redteam_target.oauth.time.monotonic", lambda: now[0])
    submitted = []
    issued = []

    def handle(request: httpx.Request) -> httpx.Response:
        if str(request.url) == TOKEN_URL:
            issued.append(request)
            return httpx.Response(
                HTTPStatus.OK,
                json={"access_token": "access", "expires_in": 10, "token_type": "Bearer"},
            )
        if request.method == "POST":
            submitted.append(request)
            return httpx.Response(HTTPStatus.OK, json={"taskid": "accepted"})
        body = (
            {}
            if now[0] == 0
            else {"finished_at": "today", "final_status": "success", "final_result": "answer"}
        )
        return httpx.Response(HTTPStatus.OK, json=body)

    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        target = AlquimiaTargetAssistant(BASE, "agent", api_key=SECRET, client=client, deadline=0)
        assert target.send("question").failed
        now[0] = 11
        assert target.send("question").content == "answer"
    assert len(submitted) == 1
    assert len(issued) == 2


def test_redirect_is_not_followed() -> None:
    requests = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if str(request.url) == TOKEN_URL:
            return httpx.Response(HTTPStatus.TEMPORARY_REDIRECT, headers={"Location": BASE})
        pytest.fail("redirect must not receive credentials")

    with httpx.Client(transport=httpx.MockTransport(handle), follow_redirects=True) as client:
        response = AlquimiaTargetAssistant(BASE, "agent", api_key=SECRET, client=client).send("q")
    assert response.failed
    assert len(requests) == 1
