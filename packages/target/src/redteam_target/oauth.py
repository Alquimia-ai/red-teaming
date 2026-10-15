"""Client-credentials authentication, resolved from a secret rather than a frozen run spec."""

from __future__ import annotations

import math
import threading
import time
from collections.abc import Generator
from http import HTTPStatus
from typing import Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError


class ClientCredentials(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    type: Literal["oauth2_client_credentials"]
    token_endpoint: str
    client_id: str = Field(min_length=1)
    client_secret: str = Field(min_length=1, repr=False)


def target_auth(credential: str | None, endpoint: str) -> httpx.Auth:
    """Keep existing opaque Bearer keys compatible; JSON credentials are explicitly typed."""
    if credential is None:
        return httpx.Auth()
    if not credential.lstrip().startswith("{"):
        return BearerAuth(credential)
    try:
        config = ClientCredentials.model_validate_json(credential)
        url = httpx.URL(config.token_endpoint)
        if url.scheme != "https" or not url.host or url.userinfo or url.query or url.fragment:
            raise ValueError
    except (ValidationError, ValueError, httpx.InvalidURL):
        raise ValueError("invalid OAuth client-credentials secret") from None
    return ClientCredentialsAuth(config, endpoint)


class BearerAuth(httpx.Auth):
    def __init__(self, token: str) -> None:
        self._token = token

    def auth_flow(self, request: httpx.Request) -> Generator[httpx.Request, httpx.Response, None]:
        request.headers["Authorization"] = f"Bearer {self._token}"
        yield request


class ClientCredentialsAuth(httpx.Auth):
    """Renew before expiry for submission AND polling; never replay an inference request.

    Client credentials obtain a new access token, not a refresh token. Endpoint failures are
    sanitized before they reach the connector's persisted transport-failure records.
    """

    requires_response_body = True

    def __init__(self, config: ClientCredentials, endpoint: str) -> None:
        self._config = config
        self._origin = self._origin_of(httpx.URL(endpoint))
        self._token = ""
        self._expires_at = 0.0
        self._lock = threading.Lock()

    @staticmethod
    def _origin_of(url: httpx.URL) -> tuple[str, str, int | None]:
        return url.scheme, url.host, url.port

    def sanitize(self, error: Exception) -> Exception:
        """HTTPX raises transport errors outside the auth generator, at the connector boundary."""
        if (
            isinstance(error, httpx.RequestError)
            and str(error.request.url) == self._config.token_endpoint
        ):
            return type(error)("OAuth token endpoint could not be reached")
        return error

    def sync_auth_flow(
        self, request: httpx.Request
    ) -> Generator[httpx.Request, httpx.Response, None]:
        if self._origin_of(request.url) != self._origin:
            raise ValueError("OAuth target origin mismatch")
        with self._lock:
            if time.monotonic() >= self._expires_at:
                token_request = httpx.Request(
                    "POST",
                    self._config.token_endpoint,
                    data={
                        "grant_type": "client_credentials",
                        "client_id": self._config.client_id,
                        "client_secret": self._config.client_secret,
                    },
                )
                started = time.monotonic()
                response = yield token_request
                response.read()
                if response.status_code != HTTPStatus.OK:
                    safe_response = httpx.Response(
                        response.status_code,
                        request=token_request,
                        json={"message": "OAuth token endpoint refused client credentials"},
                    )
                    raise httpx.HTTPStatusError(
                        "OAuth token acquisition failed",
                        request=token_request,
                        response=safe_response,
                    )
                try:
                    body = response.json()
                    token = body["access_token"]
                    lifetime = float(body["expires_in"])
                    if (
                        not isinstance(token, str)
                        or not token
                        or body["token_type"].lower() != "bearer"
                        or not math.isfinite(lifetime)
                        or lifetime <= 0
                        or any(char.isspace() for char in token)
                    ):
                        raise ValueError
                except (ValueError, KeyError, TypeError, AttributeError):
                    raise ValueError("OAuth token endpoint returned an invalid token") from None
                self._token = token
                self._expires_at = started + lifetime - min(30.0, lifetime * 0.1)
            request.headers["Authorization"] = f"Bearer {self._token}"
        response = yield request
        if response.status_code == HTTPStatus.UNAUTHORIZED:
            # Refresh on the next governed attempt, never resubmit an accepted inference here.
            with self._lock:
                if request.headers["Authorization"] == f"Bearer {self._token}":
                    self._expires_at = 0.0
