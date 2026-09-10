"""The settings read one prefix, and promise only what this build serves."""

from __future__ import annotations

import pytest

from redteam_settings.config import (
    ENV_PREFIX,
    DispatchBackend,
    SecretsBackend,
    Settings,
    StoreBackend,
    load,
)


def test_the_prefix_is_reserved_for_the_platform() -> None:
    assert ENV_PREFIX == "REDTEAM_"


def test_every_seam_is_read_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REDTEAM_STORE_BACKEND", "memory")
    monkeypatch.setenv("REDTEAM_DISPATCH_BACKEND", "k8s_job")
    monkeypatch.setenv("REDTEAM_SECRETS_BACKEND", "file")
    monkeypatch.setenv("REDTEAM_SECRETS_ROOT", "/var/run/secrets/red-teaming")
    monkeypatch.setenv("REDTEAM_S3_BUCKET", "evidence")
    monkeypatch.setenv("REDTEAM_K8S_NAMESPACE", "attacks")

    settings = load()

    assert settings.store_backend is StoreBackend.MEMORY
    assert settings.dispatch_backend is DispatchBackend.K8S_JOB
    assert settings.secrets_backend is SecretsBackend.FILE
    assert settings.secrets_root == "/var/run/secrets/red-teaming"
    assert settings.s3_bucket == "evidence"
    assert settings.k8s_namespace == "attacks"


def test_the_defaults_are_the_appliance_s(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("STORE_BACKEND", "DISPATCH_BACKEND", "SECRETS_BACKEND", "S3_BUCKET"):
        monkeypatch.delenv(f"REDTEAM_{name}", raising=False)

    settings = Settings()

    assert settings.store_backend is StoreBackend.S3
    assert settings.dispatch_backend is DispatchBackend.DOCKER
    assert settings.secrets_backend is SecretsBackend.ENV
    assert settings.s3_bucket == "red-teaming"
    assert settings.runner_image.startswith("alquimiaai/red-teaming-runner")


def test_a_value_nothing_serves_is_refused_at_load(monkeypatch: pytest.MonkeyPatch) -> None:
    """The enum is the contract the operator reads. A value it does not carry fails here, by name,
    rather than starting a process that writes evidence somewhere nobody asked for."""
    monkeypatch.setenv("REDTEAM_STORE_BACKEND", "gcs")
    with pytest.raises(ValueError, match="store_backend"):
        load()


def test_variables_outside_the_prefix_are_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STORE_BACKEND", "memory")
    monkeypatch.delenv("REDTEAM_STORE_BACKEND", raising=False)
    assert Settings().store_backend is StoreBackend.S3


def test_the_kubernetes_backend_s_knobs_have_appliance_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in (
        "K8S_RUNNER_SECRET",
        "K8S_RUNNER_CONFIG_MAP",
        "K8S_SERVICE_ACCOUNT",
        "K8S_JOB_BACKOFF_LIMIT",
        "K8S_JOB_TTL_SECONDS",
    ):
        monkeypatch.delenv(f"REDTEAM_{name}", raising=False)

    settings = Settings()

    assert settings.k8s_runner_secret == "red-teaming-runner-secrets"
    assert settings.k8s_runner_config_map is None and settings.k8s_service_account is None
    assert settings.k8s_job_backoff_limit == 2
    assert settings.k8s_job_ttl_seconds == 86400

    monkeypatch.setenv("REDTEAM_K8S_JOB_BACKOFF_LIMIT", "5")
    monkeypatch.setenv("REDTEAM_K8S_RUNNER_CONFIG_MAP", "runner-config")
    tuned = load()
    assert tuned.k8s_job_backoff_limit == 5 and tuned.k8s_runner_config_map == "runner-config"
