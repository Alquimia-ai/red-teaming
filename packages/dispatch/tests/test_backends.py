"""Every backend the settings promise is served, and nothing else is."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from redteam_dispatch import AVAILABLE, DispatchBackendUnavailable, build_dispatcher
from redteam_dispatch.docker import DockerDispatcher
from redteam_dispatch.k8s import K8sJobDispatcher
from redteam_dispatch.local import LocalSubprocessDispatcher
from redteam_settings.config import DispatchBackend, Settings


class _Resolver:
    def resolve(self, ref: str) -> str:
        return f"resolved-{ref}"


@dataclass
class _Settings:
    runner_image: str = "red-teaming-runner:local"
    docker_network: str | None = "red-teaming"
    k8s_namespace: str = "attacks"
    k8s_runner_secret: str = "runner-secrets"
    k8s_runner_config_map: str | None = "runner-config"
    k8s_store_secret: str | None = "store-creds"
    k8s_image_pull_secret: str | None = "ghcr-pull"
    k8s_service_account: str | None = "red-teaming-runner"
    k8s_job_backoff_limit: int = 3
    k8s_job_ttl_seconds: int = 600


def test_each_backend_builds_its_dispatcher() -> None:
    settings = _Settings()
    resolver = _Resolver()

    local = build_dispatcher("local_subprocess", settings, resolver=resolver)
    docker = build_dispatcher("docker", settings, resolver=resolver, env={"A": "1"})
    k8s = build_dispatcher("k8s_job", settings, resolver=resolver)

    assert isinstance(local, LocalSubprocessDispatcher)
    assert isinstance(docker, DockerDispatcher)
    assert docker._image == "red-teaming-runner:local" and docker._network == "red-teaming"
    assert docker._env == {"A": "1"}
    assert isinstance(k8s, K8sJobDispatcher)
    assert k8s._namespace == "attacks" and k8s._secret == "runner-secrets"
    assert k8s._store_secret == "store-creds" and k8s._image_pull_secret == "ghcr-pull"
    assert k8s._backoff_limit == 3 and k8s._ttl_seconds == 600


def test_the_settings_promise_exactly_what_this_build_serves() -> None:
    """A backend named in the enum and unwritten would start green, accept a run, freeze its spec
    and die at launch with the run id burned. The two lists are one."""
    assert set(AVAILABLE) == {backend.value for backend in DispatchBackend}


def test_a_backend_nothing_serves_is_refused_and_the_refusal_names_the_alternatives() -> None:
    with pytest.raises(DispatchBackendUnavailable) as refused:
        build_dispatcher("cloudrun_job", _Settings(), resolver=_Resolver())
    for available in AVAILABLE:
        assert available in str(refused.value)


def test_the_real_settings_carry_what_every_backend_reads() -> None:
    """The stand-in above mirrors the settings; this holds the mirror to the original."""
    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    for field in vars(_Settings()):
        assert hasattr(settings, field), f"settings lost {field!r}"
