"""Which dispatcher a deployment asked for, decided once.

Takes the backend as a plain string rather than the settings enum, the shape `build_store` and
`build_resolver` have, so the selection lives in one place instead of copied into every wiring
module. **Every value the settings promise is served here**, and a guard holds the two lists
together: a backend named in the enum and unwritten would start green, accept a run, freeze its spec
and then die at launch with the run id burned.
"""

from __future__ import annotations

from collections.abc import Mapping

from redteam_dispatch.dispatcher import Dispatcher
from redteam_dispatch.docker import BACKEND as DOCKER
from redteam_dispatch.docker import DockerDispatcher
from redteam_dispatch.k8s import BACKEND as K8S_JOB
from redteam_dispatch.k8s import K8sJobDispatcher
from redteam_dispatch.local import BACKEND as LOCAL_SUBPROCESS
from redteam_dispatch.local import LocalSubprocessDispatcher
from redteam_secrets.resolver import SecretResolver
from redteam_settings.config import Settings

AVAILABLE = (DOCKER, K8S_JOB, LOCAL_SUBPROCESS)
"""What this build can launch a run with. Exactly what the settings enum promises."""


class DispatchBackendUnavailable(RuntimeError):
    """A dispatch backend the settings name and this build cannot launch with. Loud rather than
    silently degraded: a fallback to another backend launches a run somewhere nobody asked for."""


def build_dispatcher(
    backend: str,
    settings: Settings,
    *,
    resolver: SecretResolver,
    env: Mapping[str, str] | None = None,
) -> Dispatcher:
    """The dispatcher this deployment asked for.

    Args:
        backend: `docker`, `k8s_job` or `local_subprocess`. The names the settings use.
        settings: Where the image, the network, the namespace and the Job's parameters come from.
        resolver: How a `secret_ref` becomes a value, for the backends that hand the runner values;
            the kubernetes backend hands it references and never calls this.
        env: What every runner this dispatcher launches gets in its environment -- the store
            wiring, and nothing secret. Per-run secrets travel per launch, by reference.

    Raises:
        DispatchBackendUnavailable: The backend is not one this build serves.
    """
    if backend == LOCAL_SUBPROCESS:
        return LocalSubprocessDispatcher(resolver, env=env)
    if backend == DOCKER:
        return DockerDispatcher(
            settings.runner_image, resolver, network=settings.docker_network, env=env
        )
    if backend == K8S_JOB:
        return K8sJobDispatcher(
            settings.runner_image,
            namespace=settings.k8s_namespace,
            secret_name=settings.k8s_runner_secret,
            env=env,
            config_map=settings.k8s_runner_config_map,
            store_secret=settings.k8s_store_secret,
            image_pull_secret=settings.k8s_image_pull_secret,
            service_account=settings.k8s_service_account,
            backoff_limit=settings.k8s_job_backoff_limit,
            ttl_seconds=settings.k8s_job_ttl_seconds,
        )
    raise DispatchBackendUnavailable(
        f"no dispatcher for the {backend!r} backend in this build. Available: "
        f"{', '.join(AVAILABLE)}. This process refuses to serve rather than accepting a run it "
        f"cannot launch."
    )
