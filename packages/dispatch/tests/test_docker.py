"""A runner as a container: created by name, handed its secrets resolved, its liveness read off the
daemon."""

from __future__ import annotations

import json
from http import HTTPStatus
from typing import Any

import httpx
import pytest

from redteam_dispatch import AlreadyRunning, DispatchError, JobState
from redteam_dispatch.docker import DockerDispatcher


class _Resolver:
    def resolve(self, ref: str) -> str:
        return f"resolved-{ref}"


class _Daemon:
    """Answers the two calls a launch makes and the one a status makes, and remembers them."""

    def __init__(
        self,
        *,
        create: int = HTTPStatus.CREATED,
        start: int = HTTPStatus.NO_CONTENT,
        inspect: tuple[int, dict[str, Any]] | None = None,
    ) -> None:
        self.requests: list[httpx.Request] = []
        self._create = create
        self._start = start
        self._inspect = inspect or (HTTPStatus.NOT_FOUND, {})

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.url.path == "/containers/create":
            return httpx.Response(self._create, json={"Id": "c0ffee"})
        if request.url.path.endswith("/start"):
            return httpx.Response(self._start)
        if request.url.path.endswith("/json"):
            status, body = self._inspect
            return httpx.Response(status, json=body)
        return httpx.Response(HTTPStatus.INTERNAL_SERVER_ERROR)

    def client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self), base_url="http://docker")


def _dispatcher(daemon: _Daemon, **kwargs: Any) -> DockerDispatcher:
    return DockerDispatcher(
        "red-teaming-runner:local",
        _Resolver(),
        network="red-teaming",
        env={"REDTEAM_STORE_BACKEND": "s3"},
        client=daemon.client,
        **kwargs,
    )


def test_a_launch_creates_a_named_container_and_starts_it() -> None:
    daemon = _Daemon()

    handle = _dispatcher(daemon).launch(
        "run-1", env={"REDTEAM_S3_BUCKET": "evidence"}, secret_refs=("TARGET_KEY",)
    )

    create, start = daemon.requests
    assert create.url.params["name"] == "redteam-run-run-1"
    body = json.loads(create.content)
    assert body["Image"] == "red-teaming-runner:local"
    assert body["Cmd"] == ["run", "run-1"], "the image's entrypoint is the runner"
    assert body["HostConfig"] == {"AutoRemove": True, "NetworkMode": "red-teaming"}
    assert set(body["Env"]) == {
        "REDTEAM_STORE_BACKEND=s3",
        "REDTEAM_S3_BUCKET=evidence",
        "TARGET_KEY=resolved-TARGET_KEY",
    }
    assert start.url.path == "/containers/c0ffee/start"
    assert handle.identifier == "c0ffee" and handle.backend == "docker"


def test_a_duplicate_name_is_the_uniqueness_invariant_working() -> None:
    with pytest.raises(AlreadyRunning, match="redteam-run-run-1"):
        _dispatcher(_Daemon(create=HTTPStatus.CONFLICT)).launch("run-1")


def test_a_missing_image_names_the_build_command() -> None:
    with pytest.raises(DispatchError, match="apps/runner/Dockerfile"):
        _dispatcher(_Daemon(create=HTTPStatus.NOT_FOUND)).launch("run-1")


def test_a_daemon_that_refuses_to_start_is_a_dispatch_error() -> None:
    with pytest.raises(DispatchError, match="refused to start"):
        _dispatcher(_Daemon(start=HTTPStatus.INTERNAL_SERVER_ERROR)).launch("run-1")


@pytest.mark.parametrize(
    ("inspect", "expected"),
    [
        ((HTTPStatus.NOT_FOUND, {}), JobState.UNKNOWN),
        ((HTTPStatus.OK, {"State": {"Status": "created"}}), JobState.PENDING),
        ((HTTPStatus.OK, {"State": {"Status": "running"}}), JobState.RUNNING),
        ((HTTPStatus.OK, {"State": {"Status": "exited", "ExitCode": 0}}), JobState.SUCCEEDED),
        ((HTTPStatus.OK, {"State": {"Status": "exited", "ExitCode": 1}}), JobState.FAILED),
        ((HTTPStatus.OK, {"State": {"Status": "dead", "ExitCode": 137}}), JobState.FAILED),
    ],
)
def test_the_container_s_state_is_the_run_s_liveness(
    inspect: tuple[int, dict[str, Any]], expected: JobState
) -> None:
    daemon = _Daemon(inspect=inspect)

    state = _dispatcher(daemon).status("run-1")

    assert state is expected
    [asked] = daemon.requests
    assert asked.url.path == "/containers/redteam-run-run-1/json"


def test_a_daemon_this_process_cannot_reach_answers_unknown() -> None:
    def _down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no socket")

    dispatcher = DockerDispatcher(
        "img",
        _Resolver(),
        client=lambda: httpx.Client(transport=httpx.MockTransport(_down), base_url="http://d"),
    )
    assert dispatcher.status("run-1") is JobState.UNKNOWN
