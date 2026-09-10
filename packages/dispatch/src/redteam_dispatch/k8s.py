"""A runner as a Kubernetes Job. The cluster and appliance backend.

A `batch/v1` Job named for the run, with `restartPolicy: Never` and a bounded `backoffLimit`: the
platform relaunches a runner that exited non-zero, and every relaunch resumes from the difference,
so a retry never repeats closed work. A duplicate launch collides on the Job's name -- the API
server answers 409 -- which is the uniqueness invariant working.

**No credential enters the Job's spec.** Every `secret_ref` the run declared becomes a
`secretKeyRef` into the deployment's runner Secret: the Job carries the key's name, the kubelet
resolves it into the pod, and a spec somebody reads back with `kubectl get job -o yaml` shows
references and never values. The platform's own wiring may come from a ConfigMap through `envFrom`,
or be passed per launch as literal environment -- that is what `env` is for, and it is for nothing
secret.

Reached over HTTPS with the pod's own service-account token, through `httpx`, like the docker
backend reaches the daemon: one kind of thing, an HTTP call, and no client library in the API image.
"""

from __future__ import annotations

import os
import ssl
from collections.abc import Callable, Mapping, Sequence
from http import HTTPStatus
from pathlib import Path
from typing import Any

import httpx

from redteam_dispatch.dispatcher import (
    AlreadyRunning,
    DispatchError,
    JobHandle,
    JobState,
    job_name,
)

BACKEND = "k8s_job"
TIMEOUT = 30.0

SERVICE_ACCOUNT_DIR = Path("/var/run/secrets/kubernetes.io/serviceaccount")
"""Where the kubelet mounts a pod's identity: its token and the cluster's CA."""

HOST_VARIABLE = "KUBERNETES_SERVICE_HOST"
PORT_VARIABLE = "KUBERNETES_SERVICE_PORT"
"""How a pod finds its own API server. Set by the kubelet in every pod, and platform configuration
rather than a credential: the token is the credential, and it is read off the mounted file."""

CONTAINER = "runner"
LABEL_NAME = "app.kubernetes.io/name"
LABEL_RUN = "red-teaming.alquimia.ai/run-id"
APP_LABEL = "red-teaming-runner"


def in_cluster_client(
    service_account_dir: Path = SERVICE_ACCOUNT_DIR,
) -> Callable[[], httpx.Client]:
    """A client for the API server the pod runs under, authenticated as the pod.

    Read at call time rather than once: a bound service-account token rotates, and a client that
    kept the token it saw at start would be refused an hour into a long-lived API process.

    Raises:
        DispatchError: This process is not running in a pod -- no API server address in its
            environment, or no token mounted -- so no Job can be created from it.
    """

    def factory() -> httpx.Client:
        host = os.environ.get(HOST_VARIABLE)
        port = os.environ.get(PORT_VARIABLE, "443")
        token_path = service_account_dir / "token"
        if not host or not token_path.is_file():
            raise DispatchError(
                "the kubernetes backend needs to run inside a pod: no API server address in the "
                "environment or no service-account token mounted. Use the docker or "
                "local_subprocess backend outside a cluster."
            )
        ca = service_account_dir / "ca.crt"
        return httpx.Client(
            base_url=f"https://{host}:{port}",
            headers={"Authorization": f"Bearer {token_path.read_text().strip()}"},
            verify=ssl.create_default_context(cafile=str(ca)) if ca.is_file() else True,
            timeout=TIMEOUT,
        )

    return factory


class K8sJobDispatcher:
    """One Job per run, named for the run, in one namespace.

    Args:
        image: The runner image; its `ENTRYPOINT` is the runner, so the container gets `args`.
        namespace: Where the Job is created. The API's own, by convention.
        secret_name: The Secret every `secret_ref` the run declares is read from, by key.
        client: How the API server is reached. In-cluster by default; a test hands in a transport.
        env: Literal, non-secret environment every runner gets -- the store's endpoint and bucket.
        config_map: A ConfigMap the runner reads its wiring from, when the deployment keeps it
            there rather than passing it here.
        service_account: The identity the runner's pod runs as. Absent takes the namespace default.
        backoff_limit: How many relaunches the platform gives a runner that exits non-zero.
        ttl_seconds: How long a finished Job stays before the platform removes it.
    """

    def __init__(
        self,
        image: str,
        *,
        namespace: str,
        secret_name: str,
        client: Callable[[], httpx.Client] | None = None,
        env: Mapping[str, str] | None = None,
        config_map: str | None = None,
        service_account: str | None = None,
        backoff_limit: int = 2,
        ttl_seconds: int = 86400,
    ) -> None:
        self._image = image
        self._namespace = namespace
        self._secret = secret_name
        self._client = client or in_cluster_client()
        self._env = dict(env or {})
        self._config_map = config_map
        self._service_account = service_account
        self._backoff_limit = backoff_limit
        self._ttl_seconds = ttl_seconds

    @property
    def _jobs(self) -> str:
        return f"/apis/batch/v1/namespaces/{self._namespace}/jobs"

    def manifest(
        self, run_id: str, *, env: Mapping[str, str] | None = None, secret_refs: Sequence[str] = ()
    ) -> dict[str, Any]:
        """The Job as it is submitted. Public so a deployment can render it without launching."""
        name = job_name(run_id)
        labels = {LABEL_NAME: APP_LABEL, LABEL_RUN: run_id}
        environment: list[dict[str, Any]] = [
            {"name": key, "value": value} for key, value in {**self._env, **(env or {})}.items()
        ]
        # A reference, never a value: the kubelet resolves the key into the pod, and the Job's spec
        # read back shows which secret the run used and nothing of what it held.
        environment.extend(
            {"name": ref, "valueFrom": {"secretKeyRef": {"name": self._secret, "key": ref}}}
            for ref in secret_refs
        )
        container: dict[str, Any] = {
            "name": CONTAINER,
            "image": self._image,
            "args": ["run", run_id],
            "env": environment,
        }
        if self._config_map:
            container["envFrom"] = [{"configMapRef": {"name": self._config_map}}]
        pod: dict[str, Any] = {"restartPolicy": "Never", "containers": [container]}
        if self._service_account:
            pod["serviceAccountName"] = self._service_account
        return {
            "apiVersion": "batch/v1",
            "kind": "Job",
            "metadata": {"name": name, "namespace": self._namespace, "labels": labels},
            "spec": {
                "backoffLimit": self._backoff_limit,
                "ttlSecondsAfterFinished": self._ttl_seconds,
                "template": {"metadata": {"labels": labels}, "spec": pod},
            },
        }

    def launch(
        self,
        run_id: str,
        *,
        env: Mapping[str, str] | None = None,
        secret_refs: Sequence[str] = (),
    ) -> JobHandle:
        name = job_name(run_id)
        body = self.manifest(run_id, env=env, secret_refs=secret_refs)
        try:
            with self._client() as client:
                created = client.post(self._jobs, json=body)
        except httpx.HTTPError as down:
            raise DispatchError(
                f"the API server could not be reached to create {name}: "
                f"{type(down).__name__}: {down}"
            ) from down
        if created.status_code == HTTPStatus.CONFLICT:
            raise AlreadyRunning(f"a Job named {name} already exists in {self._namespace!r}")
        if created.is_error:
            raise DispatchError(
                f"the API server refused to create {name} in {self._namespace!r}: "
                f"{created.status_code} {created.text[:300]}"
            )
        uid = str(((created.json().get("metadata") or {}).get("uid")) or name)
        return JobHandle(run_id=run_id, backend=BACKEND, identifier=uid)

    def status(self, run_id: str) -> JobState:
        """What the Job's status says, read off its conditions first and its counters second.

        A Job the API server does not know is `unknown` -- never created, or already removed by its
        TTL. A server this process cannot reach is `unknown` too: the platform cannot vouch for the
        run, and the caller's remedy is the same either way.
        """
        try:
            with self._client() as client:
                fetched = client.get(f"{self._jobs}/{job_name(run_id)}")
        except (httpx.HTTPError, DispatchError):
            return JobState.UNKNOWN
        if fetched.status_code == HTTPStatus.NOT_FOUND or fetched.is_error:
            return JobState.UNKNOWN
        status = fetched.json().get("status") or {}
        for condition in status.get("conditions") or ():
            if str(condition.get("status")) != "True":
                continue
            if condition.get("type") == "Complete":
                return JobState.SUCCEEDED
            if condition.get("type") == "Failed":
                return JobState.FAILED
        if int(status.get("succeeded") or 0) > 0:
            return JobState.SUCCEEDED
        if int(status.get("active") or 0) > 0:
            return JobState.RUNNING
        return JobState.PENDING
