"""A runner as an ephemeral container, through the Docker Engine API.

Over the socket with HTTP rather than by shelling out to the `docker` binary, and the first reason
is not aesthetic: the API image is a slim Python base with no docker client in it, and installing
one would put a container runtime inside the component that has to start fast. The second is that
it makes the platform backends the same kind of thing -- an HTTP call -- which is what the design
claims they are. This is the compose backend and the one closest to a Kubernetes Job: same
semantics, same lifecycle. What runs locally is the topology that ships.

**The container is removed when it exits.** That is what lets a relaunch of the same run reuse the
name: a container that stayed behind would refuse the next attempt as "already running" for a runner
that died an hour ago. The cost is that `status` answers `unknown` for a run whose container is gone
-- and that is the honest answer, because the store, not the platform, says how the run ended.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from http import HTTPStatus
from typing import Any

import httpx

from redteam_dispatch.dispatcher import (
    AlreadyRunning,
    DispatchError,
    JobHandle,
    JobState,
    job_name,
)
from redteam_secrets.resolver import SecretResolver

BACKEND = "docker"
DEFAULT_SOCKET = "/var/run/docker.sock"
TIMEOUT = 60.0

_ALIVE = frozenset({"running", "restarting", "paused", "removing"})
_PENDING = frozenset({"created"})
"""The daemon's own words for a container's state, grouped by what they mean for liveness."""


def _over_socket(socket_path: str) -> Callable[[], httpx.Client]:
    def factory() -> httpx.Client:
        return httpx.Client(
            transport=httpx.HTTPTransport(uds=socket_path),
            base_url="http://docker",
            timeout=TIMEOUT,
        )

    return factory


class DockerDispatcher:
    """Creates and starts one container per run, named for the run.

    Args:
        image: The runner image. Its `ENTRYPOINT` is the runner's console script, so the container
            is handed only the arguments.
        resolver: Turns each `secret_ref` the launch names into the value the container gets in its
            environment.
        network: Which network the container joins, so it reaches the store the API reaches.
        env: What every runner this dispatcher launches gets -- the store wiring.
        client: How the daemon is reached. The socket by default; a test hands in a transport.
    """

    def __init__(
        self,
        image: str,
        resolver: SecretResolver,
        *,
        network: str | None = None,
        env: Mapping[str, str] | None = None,
        socket_path: str = DEFAULT_SOCKET,
        client: Callable[[], httpx.Client] | None = None,
    ) -> None:
        self._image = image
        self._resolver = resolver
        self._network = network
        self._env = dict(env or {})
        self._client = client or _over_socket(socket_path)

    def launch(
        self,
        run_id: str,
        *,
        env: Mapping[str, str] | None = None,
        secret_refs: Sequence[str] = (),
    ) -> JobHandle:
        name = job_name(run_id)
        environment = {
            **self._env,
            **(env or {}),
            **{ref: self._resolver.resolve(ref) for ref in secret_refs},
        }
        body: dict[str, Any] = {
            "Image": self._image,
            # The argument list: the image's `ENTRYPOINT` is the runner itself.
            "Cmd": ["run", run_id],
            "Env": [f"{k}={v}" for k, v in environment.items()],
            "HostConfig": {"AutoRemove": True},
        }
        if self._network:
            body["HostConfig"]["NetworkMode"] = self._network

        try:
            with self._client() as client:
                created = client.post("/containers/create", params={"name": name}, json=body)
                started = self._start(client, created, name)
        except httpx.HTTPError as down:
            raise DispatchError(
                f"the docker daemon could not be reached to launch {name}: "
                f"{type(down).__name__}: {down}. Is the socket mounted, and may this process "
                f"open it?"
            ) from down
        return JobHandle(run_id=run_id, backend=BACKEND, identifier=started)

    def _start(self, client: httpx.Client, created: httpx.Response, name: str) -> str:
        """Read the daemon's answer to the create, then start what it created."""
        if created.status_code == HTTPStatus.CONFLICT:
            # A duplicate name refused by the daemon is the uniqueness invariant working.
            raise AlreadyRunning(f"a container named {name} already exists")
        if created.status_code == HTTPStatus.NOT_FOUND:
            raise DispatchError(
                f"the runner image {self._image!r} is not on the daemon. Build it with "
                f"docker build -t {self._image} -f apps/runner/Dockerfile ."
            )
        if created.is_error:
            raise DispatchError(f"docker refused to create {name}: {created.text}")

        container_id = str(created.json()["Id"])
        started = client.post(f"/containers/{container_id}/start")
        if started.is_error:
            raise DispatchError(f"docker refused to start {name}: {started.text}")
        return container_id

    def status(self, run_id: str) -> JobState:
        """What the daemon says about the run's container.

        `unknown` when there is none -- which, with `AutoRemove`, is also what a finished runner
        looks like a moment after it exits. A daemon this process cannot reach is `unknown` too:
        the answer is "the platform cannot vouch for it", and the caller's remedy is the same.
        """
        name = job_name(run_id)
        try:
            with self._client() as client:
                inspected = client.get(f"/containers/{name}/json")
        except httpx.HTTPError:
            return JobState.UNKNOWN
        if inspected.status_code == HTTPStatus.NOT_FOUND or inspected.is_error:
            return JobState.UNKNOWN
        state = inspected.json().get("State") or {}
        status = str(state.get("Status", "")).lower()
        if status in _ALIVE:
            return JobState.RUNNING
        if status in _PENDING:
            return JobState.PENDING
        if status in ("exited", "dead"):
            return JobState.SUCCEEDED if int(state.get("ExitCode", 1)) == 0 else JobState.FAILED
        return JobState.UNKNOWN
