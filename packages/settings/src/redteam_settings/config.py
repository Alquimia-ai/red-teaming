"""Settings. Environment variables only, and the three seams that make the images portable.

The images do not change between the local stack, a cloud cluster and the appliance. Three
variables choose a backend -- where evidence is stored, how a runner is launched, where secrets are
read from -- and that is the whole portability mechanism, concentrated here on purpose rather than
spread across the code as conditionals.

Every enum below names only what this build serves. A value the settings promise and nothing
implements is worse than a missing value: the operator reads the enum as the contract, the process
starts green, and the evidence lands somewhere nobody asked for.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic_settings import BaseSettings, SettingsConfigDict

ENV_PREFIX = "REDTEAM_"
"""Reserved for runtime configuration. A `secret_ref` may not start with it, so a spec can never
address the platform's own configuration as if it were a credential."""


class StoreBackend(StrEnum):
    S3 = "s3"
    """Any S3-compatible service: MinIO on the appliance, the provider's own in the cloud."""

    MEMORY = "memory"
    """In-process. The tests', and a single-process rehearsal's."""


class DispatchBackend(StrEnum):
    DOCKER = "docker"
    K8S_JOB = "k8s_job"
    LOCAL_SUBPROCESS = "local_subprocess"


class SecretsBackend(StrEnum):
    ENV = "env"
    FILE = "file"
    """A mounted secret is a directory of files, one per secret. The Kubernetes path."""


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix=ENV_PREFIX, extra="ignore")

    store_backend: StoreBackend = StoreBackend.S3
    dispatch_backend: DispatchBackend = DispatchBackend.DOCKER
    secrets_backend: SecretsBackend = SecretsBackend.ENV

    secrets_root: str | None = None
    """Where the `file` backend reads from. No default: a wrong root answers "not found" for every
    secret and reads as missing configuration rather than as a wrong path."""

    s3_endpoint: str | None = None
    """Absent for the provider's own S3, whose endpoint the client knows; set for MinIO and any
    other compatible service."""

    s3_bucket: str = "red-teaming"
    s3_region: str | None = None
    s3_access_key: str | None = None
    s3_secret_key: str | None = None
    """Absent together for a deployment that authenticates through the platform -- an IAM role, a
    workload identity -- and lets the client's default credential chain answer."""

    runner_image: str = "ghcr.io/alquimia-ai/red-teaming-runner:latest"
    """The image one run is launched from. One process per run, whatever the backend. Published as
    a package of the repository on GitHub's container registry; a deployment that pins names the
    version or the `sha-<7>` tag here."""

    docker_network: str | None = None
    """Which network a launched container joins, for the docker backend. A field rather than an
    environment read at the wiring site: the settings are the whole portability mechanism, so a
    variable read somewhere else is one nobody finds."""

    k8s_namespace: str = "red-teaming"
    """Where the k8s backend creates a run's Job. The API's own namespace, by convention."""

    k8s_runner_secret: str = "red-teaming-runner-secrets"
    """The Secret a run's `secret_ref`s are read from. Each reference the spec names becomes a
    `secretKeyRef` into this Secret on the Job -- a key, never a value, in the Job's spec."""

    k8s_runner_config_map: str | None = None
    """A ConfigMap the Job reads its `REDTEAM_*` wiring from, when the deployment keeps it there
    rather than passing it per launch."""

    k8s_service_account: str | None = None
    """The service account a run's pod runs as. Absent takes the namespace's default."""

    k8s_job_backoff_limit: int = 2
    """How many times the platform relaunches a failed runner before giving the run up. Every
    relaunch resumes from the difference, so a retry never repeats closed work."""

    k8s_job_ttl_seconds: int = 86400
    """How long a finished Job stays for inspection before the platform removes it. A day: long
    enough to read the log of a runner that died, short enough that the namespace does not fill."""

    brain_registry_insecure: bool = False
    """Whether the brain registry may be reached over plain HTTP. For a local registry only."""

    brain_registry_secret_ref: str | None = None
    """The reference the secret resolver looks up for registry credentials, as `user:token`. Absent
    for a public registry, which is the only case that needs none."""


def load() -> Settings:
    return Settings()
