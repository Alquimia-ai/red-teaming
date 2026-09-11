"""The wiring: what the API hands the runner it launches."""

from __future__ import annotations

from redteam_api.deps import runner_env
from redteam_settings.config import DispatchBackend, SecretsBackend, Settings, StoreBackend


def test_the_runner_reads_its_secrets_from_its_environment_whatever_the_api_s_backend() -> None:
    """The values a launch hands over -- resolved by the API, or referenced into a Job -- land as
    environment variables. Forwarding a `file` backend would point the runner at a directory nothing
    mounts into its container."""
    api = Settings(
        store_backend=StoreBackend.S3,
        dispatch_backend=DispatchBackend.DOCKER,
        secrets_backend=SecretsBackend.FILE,
        secrets_root="/run/secrets",
        s3_endpoint="http://minio:9000",
        s3_access_key="ak",
        s3_secret_key="sk",
    )

    env = runner_env(api)

    assert env["REDTEAM_SECRETS_BACKEND"] == "env"
    assert "REDTEAM_SECRETS_ROOT" not in env
    assert (
        env["REDTEAM_STORE_BACKEND"] == "s3" and env["REDTEAM_S3_ENDPOINT"] == "http://minio:9000"
    )
    assert env["REDTEAM_S3_ACCESS_KEY"] == "ak" and env["REDTEAM_S3_SECRET_KEY"] == "sk"


def test_on_a_cluster_the_store_s_credentials_never_travel_in_the_job_spec() -> None:
    """The runner's pod reads them from the Secret the deployment mounts; the API writes no
    credential into a Job."""
    api = Settings(dispatch_backend=DispatchBackend.K8S_JOB, s3_access_key="ak", s3_secret_key="sk")

    env = runner_env(api)

    assert "REDTEAM_S3_ACCESS_KEY" not in env and "REDTEAM_S3_SECRET_KEY" not in env
    assert env["REDTEAM_S3_BUCKET"] == "red-teaming"


def test_optional_wiring_is_absent_rather_than_empty() -> None:
    env = runner_env(Settings(dispatch_backend=DispatchBackend.LOCAL_SUBPROCESS))
    assert "REDTEAM_S3_ENDPOINT" not in env and "REDTEAM_BRAIN_REGISTRY_SECRET_REF" not in env
    assert env["REDTEAM_BRAIN_REGISTRY_INSECURE"] == "false"
