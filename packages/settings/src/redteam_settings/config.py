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

    runner_image: str = "alquimiaai/red-teaming-runner:latest"
    """The image one run is launched from. One process per run, whatever the backend."""

    docker_network: str | None = None
    """Which network a launched container joins, for the docker backend. A field rather than an
    environment read at the wiring site: the settings are the whole portability mechanism, so a
    variable read somewhere else is one nobody finds."""

    k8s_namespace: str = "red-teaming"
    """Where the k8s backend creates a run's Job. The API's own namespace, by convention."""

    brain_registry_insecure: bool = False
    """Whether the brain registry may be reached over plain HTTP. For a local registry only."""

    brain_registry_secret_ref: str | None = None
    """The reference the secret resolver looks up for registry credentials, as `user:token`. Absent
    for a public registry, which is the only case that needs none."""


def load() -> Settings:
    return Settings()
