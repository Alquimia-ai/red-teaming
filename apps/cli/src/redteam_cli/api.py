"""Talking to the API. Every question the command line asks is one of these."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import httpx

TIMEOUT = 30.0


class ApiError(RuntimeError):
    """The API answered with an error. The detail is what it said, verbatim: the gate's refusals
    are written to be read by the person who sent the request."""

    def __init__(self, status: int, detail: str) -> None:
        super().__init__(f"{status}: {detail}")
        self.status = status
        self.detail = detail


class Unreachable(RuntimeError):
    def __init__(self, base_url: str, why: str) -> None:
        super().__init__(
            f"the API at {base_url} did not answer ({why}); is the stack up? `redteam local status`"
        )


def transport() -> httpx.BaseTransport | None:
    """How requests leave the process. `None` is the network; a test hands in a mock."""
    return None


def client(base_url: str) -> httpx.Client:
    return httpx.Client(base_url=base_url, timeout=TIMEOUT, transport=transport())


class Api:
    def __init__(self, base_url: str, *, make: Callable[[str], httpx.Client] = client) -> None:
        self._base_url = base_url
        self._make = make

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        try:
            with self._make(self._base_url) as http:
                response = http.request(method, path, **kwargs)
        except httpx.HTTPError as down:
            raise Unreachable(self._base_url, f"{type(down).__name__}: {down}") from down
        if response.is_error:
            try:
                detail = response.json().get("detail", response.text)
            except ValueError:
                detail = response.text
            raise ApiError(response.status_code, str(detail))
        return response.json() if response.content else None

    # ---- health and assets --------------------------------------------------------------------

    def health(self) -> dict[str, Any]:
        return dict(self._request("GET", "/healthz"))

    def validate_bundle(self, body: dict[str, Any]) -> dict[str, Any]:
        return dict(self._request("POST", "/catalogues:validate", json=body))

    def publish_bundle(self, body: dict[str, Any]) -> dict[str, Any]:
        return dict(self._request("POST", "/catalogues", json=body))

    def catalogues(self) -> dict[str, list[int]]:
        return dict(self._request("GET", "/catalogues"))

    def publish_prior(self, name: str, phrasings: list[str]) -> dict[str, Any]:
        return dict(self._request("POST", "/priors", json={"name": name, "phrasings": phrasings}))

    def probes(self, digest: str) -> list[dict[str, Any]]:
        return list(self._request("GET", f"/probes/{digest}"))

    # ---- runs ---------------------------------------------------------------------------------

    def validate_run(self, spec: dict[str, Any]) -> dict[str, Any]:
        return dict(self._request("POST", "/runs:validate", json=spec))

    def start_run(self, spec: dict[str, Any]) -> dict[str, Any]:
        return dict(self._request("POST", "/runs", json=spec))

    def runs(self) -> list[str]:
        return list(self._request("GET", "/runs")["runs"])

    def status(self, run_id: str) -> dict[str, Any]:
        return dict(self._request("GET", f"/runs/{run_id}"))

    def result(self, run_id: str) -> dict[str, Any]:
        return dict(self._request("GET", f"/runs/{run_id}/result"))

    def resume(self, run_id: str) -> dict[str, Any]:
        return dict(self._request("POST", f"/runs/{run_id}:resume"))


class Receiver:
    """The local stack's webhook receiver, which keeps every delivery it acknowledged."""

    def __init__(self, base_url: str, *, make: Callable[[str], httpx.Client] = client) -> None:
        self._base_url = base_url
        self._make = make

    def received(self, run_id: str) -> list[dict[str, Any]]:
        try:
            with self._make(self._base_url) as http:
                response = http.get("/received", params={"run_id": run_id})
        except httpx.HTTPError as down:
            raise Unreachable(self._base_url, f"{type(down).__name__}: {down}") from down
        if response.is_error:
            raise ApiError(response.status_code, response.text)
        return list(response.json())
