"""A runner as a Job: named for the run, secrets by reference, liveness off the Job's status."""

from __future__ import annotations

import json
from http import HTTPStatus
from pathlib import Path
from typing import Any

import httpx
import pytest

from redteam_dispatch import AlreadyRunning, DispatchError, JobState
from redteam_dispatch.k8s import K8sJobDispatcher, in_cluster_client

JOBS = "/apis/batch/v1/namespaces/attacks/jobs"


class _ApiServer:
    def __init__(
        self, *, create: int = HTTPStatus.CREATED, get: tuple[int, dict[str, Any]] | None = None
    ) -> None:
        self.requests: list[httpx.Request] = []
        self._create = create
        self._get = get or (HTTPStatus.NOT_FOUND, {})

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.method == "POST":
            return httpx.Response(self._create, json={"metadata": {"uid": "uid-1"}})
        status, body = self._get
        return httpx.Response(status, json=body)

    def client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self), base_url="https://k8s")


def _dispatcher(server: _ApiServer, **overrides: Any) -> K8sJobDispatcher:
    options: dict[str, Any] = {
        "namespace": "attacks",
        "secret_name": "runner-secrets",
        "client": server.client,
        "env": {"REDTEAM_STORE_BACKEND": "s3"},
        "config_map": "runner-config",
        "store_secret": "store-creds",
        "image_pull_secret": "ghcr-pull",
        "service_account": "red-teaming-runner",
        "backoff_limit": 2,
        "ttl_seconds": 3600,
    }
    options.update(overrides)
    return K8sJobDispatcher("ghcr.io/alquimia-ai/red-teaming-runner:1.0.0", **options)


def test_a_launch_submits_one_job_named_for_the_run() -> None:
    server = _ApiServer()

    handle = _dispatcher(server).launch(
        "run-1", env={"REDTEAM_S3_BUCKET": "evidence"}, secret_refs=("TARGET_KEY", "JUDGE_KEY")
    )

    [posted] = server.requests
    assert posted.url.path == JOBS
    job = json.loads(posted.content)
    assert (job["apiVersion"], job["kind"]) == ("batch/v1", "Job")
    assert job["metadata"]["name"] == "redteam-run-run-1"
    assert job["metadata"]["namespace"] == "attacks"
    assert job["metadata"]["labels"]["red-teaming.alquimia.ai/run-id"] == "run-1"
    spec = job["spec"]
    assert spec["backoffLimit"] == 2 and spec["ttlSecondsAfterFinished"] == 3600
    pod = spec["template"]["spec"]
    assert pod["restartPolicy"] == "Never"
    assert pod["serviceAccountName"] == "red-teaming-runner"
    [container] = pod["containers"]
    assert container["image"] == "ghcr.io/alquimia-ai/red-teaming-runner:1.0.0"
    assert container["args"] == ["run", "run-1"], "the image's entrypoint is the runner"
    assert container["envFrom"] == [
        {"configMapRef": {"name": "runner-config"}},
        {"secretRef": {"name": "store-creds"}},
    ]
    assert pod["imagePullSecrets"] == [{"name": "ghcr-pull"}]
    assert handle.identifier == "uid-1" and handle.backend == "k8s_job"


def test_no_credential_enters_the_job_spec() -> None:
    """Every reference becomes a `secretKeyRef`; the Job carries the key's name and never a value.
    Read back with `kubectl get job -o yaml`, it shows which secret the run used and nothing of what
    it held."""
    server = _ApiServer()

    _dispatcher(server).launch("run-1", secret_refs=("TARGET_KEY",))

    job = json.loads(server.requests[0].content)
    [container] = job["spec"]["template"]["spec"]["containers"]
    by_name = {entry["name"]: entry for entry in container["env"]}
    assert by_name["REDTEAM_STORE_BACKEND"] == {"name": "REDTEAM_STORE_BACKEND", "value": "s3"}
    assert by_name["TARGET_KEY"] == {
        "name": "TARGET_KEY",
        "valueFrom": {"secretKeyRef": {"name": "runner-secrets", "key": "TARGET_KEY"}},
    }
    assert "resolved" not in server.requests[0].content.decode()


def test_optional_wiring_is_absent_when_not_declared() -> None:
    server = _ApiServer()
    _dispatcher(
        server,
        config_map=None,
        store_secret=None,
        image_pull_secret=None,
        service_account=None,
        env=None,
    ).launch("run-1")

    job = json.loads(server.requests[0].content)
    pod = job["spec"]["template"]["spec"]
    assert "serviceAccountName" not in pod and "imagePullSecrets" not in pod
    assert "envFrom" not in pod["containers"][0]
    assert pod["containers"][0]["env"] == []


def test_a_duplicate_job_is_the_uniqueness_invariant_working() -> None:
    with pytest.raises(AlreadyRunning, match="redteam-run-run-1"):
        _dispatcher(
            _ApiServer(create=HTTPStatus.CONFLICT, get=(HTTPStatus.OK, {"status": {"active": 1}}))
        ).launch("run-1")


def test_a_server_that_refuses_is_a_dispatch_error_carrying_its_answer() -> None:
    with pytest.raises(DispatchError, match="403"):
        _dispatcher(_ApiServer(create=HTTPStatus.FORBIDDEN)).launch("run-1")


@pytest.mark.parametrize(
    ("answer", "expected"),
    [
        ((HTTPStatus.NOT_FOUND, {}), JobState.UNKNOWN),
        ((HTTPStatus.OK, {"status": {}}), JobState.PENDING),
        ((HTTPStatus.OK, {"status": {"active": 1}}), JobState.RUNNING),
        ((HTTPStatus.OK, {"status": {"active": 1, "failed": 1}}), JobState.RUNNING),
        ((HTTPStatus.OK, {"status": {"succeeded": 1}}), JobState.SUCCEEDED),
        (
            (
                HTTPStatus.OK,
                {"status": {"conditions": [{"type": "Complete", "status": "True"}]}},
            ),
            JobState.SUCCEEDED,
        ),
        (
            (
                HTTPStatus.OK,
                {"status": {"failed": 3, "conditions": [{"type": "Failed", "status": "True"}]}},
            ),
            JobState.FAILED,
        ),
        (
            (
                HTTPStatus.OK,
                {"status": {"active": 1, "conditions": [{"type": "Failed", "status": "False"}]}},
            ),
            JobState.RUNNING,
        ),
    ],
)
def test_the_job_s_status_is_the_run_s_liveness(
    answer: tuple[int, dict[str, Any]], expected: JobState
) -> None:
    server = _ApiServer(get=answer)

    state = _dispatcher(server).status("run-1")

    assert state is expected
    [asked] = server.requests
    assert asked.url.path == f"{JOBS}/redteam-run-run-1"


def test_a_server_this_process_cannot_reach_is_a_dispatch_error_at_launch() -> None:
    def _down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route")

    dispatcher = _dispatcher(
        _ApiServer(),
        client=lambda: httpx.Client(transport=httpx.MockTransport(_down), base_url="https://k"),
    )
    with pytest.raises(DispatchError, match="no route"):
        dispatcher.launch("run-1")


def test_a_server_this_process_cannot_reach_answers_unknown() -> None:
    def _down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route")

    dispatcher = _dispatcher(
        _ApiServer(),
        client=lambda: httpx.Client(transport=httpx.MockTransport(_down), base_url="https://k"),
    )
    assert dispatcher.status("run-1") is JobState.UNKNOWN


def test_outside_a_pod_a_launch_says_so_and_a_status_is_unknown(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("KUBERNETES_SERVICE_HOST", raising=False)
    dispatcher = _dispatcher(_ApiServer(), client=in_cluster_client(tmp_path))

    with pytest.raises(DispatchError, match="inside a pod"):
        dispatcher.launch("run-1")
    assert dispatcher.status("run-1") is JobState.UNKNOWN


def test_inside_a_pod_the_client_speaks_to_its_own_server_as_itself(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The address from the kubelet's environment, the token off the mounted file -- read at call
    time, because a bound token rotates."""
    monkeypatch.setenv("KUBERNETES_SERVICE_HOST", "10.0.0.1")
    monkeypatch.setenv("KUBERNETES_SERVICE_PORT", "6443")
    (tmp_path / "token").write_text("tok-1\n")
    # No `ca.crt` mounted: the cluster's CA is a real certificate or nothing, and this test is
    # about the address and the token. Without one, the system's trust store stands.
    factory = in_cluster_client(tmp_path)

    with factory() as client:
        assert str(client.base_url) == "https://10.0.0.1:6443"
        assert client.headers["Authorization"] == "Bearer tok-1"

    (tmp_path / "token").write_text("tok-2\n")
    with factory() as client:
        assert client.headers["Authorization"] == "Bearer tok-2", "rotated tokens are read"


def _terminal_job(condition: str = "Failed") -> dict[str, Any]:
    return {
        "metadata": {
            "uid": "old",
            "resourceVersion": "1",
            "labels": {
                "app.kubernetes.io/name": "red-teaming-runner",
                "red-teaming.alquimia.ai/run-id": "run-1",
            },
        },
        "status": {"conditions": [{"type": condition, "status": "True"}]},
    }


class _ReplacingServer:
    def __init__(self, condition: str = "Failed") -> None:
        self.job: dict[str, Any] | None = _terminal_job(condition)
        self.pods: list[dict[str, Any]] = []
        self.created = 0
        self.deleted: list[dict[str, Any]] = []
        self.replacement_wins = False
        self.waiting = False
        self.refuse_pods = False

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/pods"):
            assert request.url.params["labelSelector"] == "red-teaming.alquimia.ai/run-id=run-1"
            return httpx.Response(
                HTTPStatus.FORBIDDEN if self.refuse_pods else HTTPStatus.OK,
                json={"items": self.pods},
            )
        if request.method == "POST":
            if self.job is not None:
                return httpx.Response(HTTPStatus.CONFLICT)
            self.created += 1
            self.job = {"metadata": {"uid": "new", "resourceVersion": "2"}, "status": {"active": 1}}
            return httpx.Response(HTTPStatus.CREATED, json=self.job)
        if request.method == "DELETE":
            body = json.loads(request.content)
            self.deleted.append(body)
            if self.replacement_wins:
                self.replacement_wins = False
                self.created += 1
                self.job = {
                    "metadata": {"uid": "new", "resourceVersion": "2"},
                    "status": {"active": 1},
                }
                return httpx.Response(HTTPStatus.CONFLICT)
            assert self.job is not None
            assert body["preconditions"] == {
                "uid": self.job["metadata"]["uid"],
                "resourceVersion": "1",
            }
            if self.waiting:
                self.job["metadata"]["deletionTimestamp"] = "now"
            else:
                self.job = None
            return httpx.Response(HTTPStatus.OK)
        return (
            httpx.Response(HTTPStatus.OK, json=self.job)
            if self.job
            else httpx.Response(HTTPStatus.NOT_FOUND)
        )

    def client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self), base_url="https://k8s")


@pytest.mark.parametrize("condition", ["Failed", "Complete"])
def test_terminal_jobs_can_be_replaced_before_ttl(condition: str) -> None:
    server = _ReplacingServer(condition)
    dispatcher = _dispatcher(_ApiServer(), client=server.client)
    assert dispatcher.status("run-1") is (
        JobState.FAILED if condition == "Failed" else JobState.SUCCEEDED
    )
    assert dispatcher.launch("run-1").identifier == "new"
    assert dispatcher.status("run-1") is JobState.RUNNING
    assert server.created == 1 and len(server.deleted) == 1
    assert server.deleted[0]["propagationPolicy"] == "Foreground"
    with pytest.raises(AlreadyRunning):
        dispatcher.launch("run-1")
    assert server.created == 1


def test_a_concurrent_resumer_cannot_delete_the_winners_new_job() -> None:
    server = _ReplacingServer()
    server.replacement_wins = True
    dispatcher = _dispatcher(_ApiServer(), client=server.client)
    with pytest.raises(AlreadyRunning):
        dispatcher.launch("run-1")
    assert server.created == 1 and len(server.deleted) == 1
    assert server.deleted[0]["preconditions"]["uid"] == "old"
    assert dispatcher.status("run-1") is JobState.RUNNING


@pytest.mark.parametrize("phase", ["Running", "Pending", "Unknown"])
def test_terminal_condition_does_not_allow_overlapping_live_pods(phase: str) -> None:
    server = _ReplacingServer()
    server.pods = [{"status": {"phase": phase}}]
    with pytest.raises(DispatchError, match="unfinished Pods"):
        _dispatcher(_ApiServer(), client=server.client).launch("run-1")
    assert server.created == 0 and server.deleted == []


def test_an_unfinished_deletion_is_retryable_not_a_second_job(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import time

    monkeypatch.setattr(time, "sleep", lambda _: None)
    server = _ReplacingServer()
    server.waiting = True
    dispatcher = _dispatcher(_ApiServer(), client=server.client)
    for _ in range(2):
        with pytest.raises(DispatchError, match="still being removed"):
            dispatcher.launch("run-1")
    assert server.created == 0 and len(server.deleted) == 1


def test_unavailable_pod_status_cannot_authorize_replacement() -> None:
    server = _ReplacingServer()
    server.refuse_pods = True
    with pytest.raises(DispatchError, match="cannot inspect Pods"):
        _dispatcher(_ApiServer(), client=server.client).launch("run-1")
    assert server.created == 0 and server.deleted == []


def test_two_simultaneous_resumers_launch_exactly_one_runner() -> None:
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier, Lock

    barrier, lock = Barrier(2), Lock()

    class ConcurrentServer(_ReplacingServer):
        def __call__(self, request: httpx.Request) -> httpx.Response:
            if request.method == "DELETE":
                barrier.wait(timeout=5)
            with lock:
                if request.method == "DELETE":
                    if self.job is None:
                        return httpx.Response(HTTPStatus.NOT_FOUND)
                    wanted = json.loads(request.content)["preconditions"]["uid"]
                    if self.job["metadata"]["uid"] != wanted:
                        return httpx.Response(HTTPStatus.CONFLICT)
                return super().__call__(request)

    server = ConcurrentServer()

    def resume() -> str:
        try:
            return _dispatcher(_ApiServer(), client=server.client).launch("run-1").identifier
        except AlreadyRunning:
            return "already-running"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: resume(), range(2)))
    assert sorted(results) == ["already-running", "new"]
    assert server.created == 1
    assert len(server.deleted) == 1
