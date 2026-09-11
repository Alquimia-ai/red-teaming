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
import time
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
        store_secret: A Secret the runner reads the store's credentials from, whole -- the
            platform's credential, apart from the run's references.
        image_pull_secret: The registry credential the pod pulls the runner image with.
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
        store_secret: str | None = None,
        image_pull_secret: str | None = None,
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
        self._store_secret = store_secret
        self._image_pull_secret = image_pull_secret
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
        env_from: list[dict[str, Any]] = []
        if self._config_map:
            env_from.append({"configMapRef": {"name": self._config_map}})
        if self._store_secret:
            # The store's credentials, whole: the platform's, and the same ones the API holds.
            env_from.append({"secretRef": {"name": self._store_secret}})
        if env_from:
            container["envFrom"] = env_from
        pod: dict[str, Any] = {"restartPolicy": "Never", "containers": [container]}
        if self._service_account:
            pod["serviceAccountName"] = self._service_account
        if self._image_pull_secret:
            pod["imagePullSecrets"] = [{"name": self._image_pull_secret}]
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
                for _ in range(3):
                    created = client.post(self._jobs, json=body)
                    if created.status_code == HTTPStatus.CONFLICT:
                        self._remove_finished(client, run_id)
                        continue
                    if created.is_error:
                        raise DispatchError(
                            f"the API server refused to create {name}: "
                            f"{created.status_code} {created.text[:300]}"
                        )
                    uid = str(((created.json().get("metadata") or {}).get("uid")) or name)
                    return JobHandle(run_id=run_id, backend=BACKEND, identifier=uid)
        except httpx.HTTPError as down:
            raise DispatchError(
                f"the API server could not be reached to create {name}: "
                f"{type(down).__name__}: {down}"
            ) from down
        raise DispatchError(f"Job {name} changed during launch; retry the request")

    def _remove_finished(self, client: httpx.Client, run_id: str) -> None:
        """Remove only the observed terminal Job, never another request's replacement."""
        name = job_name(run_id)
        path = f"{self._jobs}/{name}"
        fetched = client.get(path)
        if fetched.status_code == HTTPStatus.NOT_FOUND:
            return  # TTL cleanup or another resumer removed it; race on the same name again.
        if fetched.is_error:
            raise DispatchError(f"cannot inspect Job {name}: {fetched.status_code}")
        job = fetched.json()
        metadata = job.get("metadata") or {}
        if metadata.get("deletionTimestamp"):
            raise DispatchError(f"Job {name} is still being removed; retry the request")
        conditions = (job.get("status") or {}).get("conditions") or []
        terminal = any(
            condition.get("type") in {"Failed", "Complete"}
            and str(condition.get("status")) == "True"
            for condition in conditions
        )
        if not terminal:
            raise AlreadyRunning(f"a Job named {name} is still active in {self._namespace!r}")
        labels = metadata.get("labels") or {}
        if labels.get(LABEL_NAME) != APP_LABEL or labels.get(LABEL_RUN) != run_id:
            raise DispatchError(f"Job {name} is not a managed runner; refusing replacement")
        uid = metadata.get("uid")
        revision = metadata.get("resourceVersion")
        if not uid or not revision:
            raise DispatchError(f"Job {name} has no verifiable identity; refusing replacement")
        # Older Kubernetes releases can mark a Job terminal while its Pods still run.
        pods = client.get(
            f"/api/v1/namespaces/{self._namespace}/pods",
            params={"labelSelector": f"{LABEL_RUN}={run_id}"},
        )
        if pods.is_error:
            raise DispatchError(f"cannot inspect Pods for Job {name}: {pods.status_code}")
        items = pods.json().get("items")
        if not isinstance(items, list) or pods.json().get("metadata", {}).get("continue"):
            raise DispatchError(f"incomplete Pod listing for Job {name}; retry the request")
        if any(
            (pod.get("status") or {}).get("phase") not in {"Failed", "Succeeded"} for pod in items
        ):
            raise DispatchError(f"Job {name} still has unfinished Pods; retry the request")
        deleted = client.request(
            "DELETE",
            path,
            json={
                "apiVersion": "v1",
                "kind": "DeleteOptions",
                "preconditions": {"uid": uid, "resourceVersion": revision},
                "propagationPolicy": "Foreground",
            },
        )
        if deleted.status_code in {HTTPStatus.NOT_FOUND, HTTPStatus.CONFLICT}:
            return  # A concurrent resumer won; re-read after trying the unique name.
        if deleted.is_error:
            raise DispatchError(f"cannot remove terminal Job {name}: {deleted.status_code}")
        # Bound the wait; an unresolved deletion is not permission to create another runner.
        for _ in range(5):
            remaining = client.get(path)
            if remaining.status_code == HTTPStatus.NOT_FOUND:
                return
            if remaining.is_error:
                raise DispatchError(f"cannot verify removal of Job {name}")
            if (remaining.json().get("metadata") or {}).get("uid") != uid:
                return  # The name already belongs to a concurrent resumer's Job.
            time.sleep(0.1)
        raise DispatchError(f"Job {name} is still being removed; retry the request")

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
