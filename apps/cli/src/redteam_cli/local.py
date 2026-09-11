"""The local stack, through docker compose.

The compose file ships with the command line, so `redteam local up` works from a wheel or a zipapp
with no checkout beside it; in a checkout the file under `deploy/compose` is the one used, so an
edit there is what runs. `down` never removes volumes: the store is the evidence, and a local stack
brought down and up again keeps every run it accepted.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Mapping
from pathlib import Path

from redteam_cli.workspace import Workspace, environment

LOCAL_RUNNER_IMAGE = "red-teaming-runner:local"
RUNNER_DOCKERFILE = Path("apps") / "runner" / "Dockerfile"


class NoDocker(RuntimeError):
    def __init__(self) -> None:
        super().__init__("docker is not on PATH; the local stack needs a docker daemon and compose")


def compose_file() -> Path:
    """The compose file to run: the checkout's when this runs from one, the packaged copy
    otherwise."""
    here = Path(__file__).resolve()
    for candidate in here.parents:
        checkout = candidate / "deploy" / "compose" / "docker-compose.yml"
        if checkout.is_file() and (candidate / "pyproject.toml").is_file():
            return checkout
    packaged = here.parent / "deploy" / "compose" / "docker-compose.yml"
    if packaged.is_file():
        return packaged
    raise FileNotFoundError("no docker-compose.yml ships with this command line")


def repository_root() -> Path | None:
    """The checkout the compose file lives in, when it does: what `--build` builds from."""
    found = compose_file()
    root = found.parents[2]
    return root if (root / "pyproject.toml").is_file() else None


def compose(workspace: Workspace, *args: str, env: Mapping[str, str] | None = None) -> None:
    if shutil.which("docker") is None:
        raise NoDocker()
    command = [
        "docker",
        "compose",
        "-f",
        str(compose_file()),
        "--project-name",
        workspace.config.compose_project,
        *args,
    ]
    subprocess.run(command, check=True, env={**os.environ, **environment(workspace), **(env or {})})


def up(workspace: Workspace, *, build: bool = False) -> None:
    """Bring the stack up. With `build`, the API and the runner images are built from the checkout
    and the runner's tag is what the API launches; without it, the published images are pulled."""
    env: dict[str, str] = {}
    if build:
        root = repository_root()
        if root is None:
            raise FileNotFoundError("--build needs a checkout; this command line runs from a wheel")
        subprocess.run(
            [
                "docker",
                "build",
                "-t",
                LOCAL_RUNNER_IMAGE,
                "-f",
                str(root / RUNNER_DOCKERFILE),
                str(root),
            ],
            check=True,
        )
        env["REDTEAM_RUNNER_IMAGE"] = LOCAL_RUNNER_IMAGE
        compose(workspace, "up", "-d", "--build", env=env)
        return
    compose(workspace, "up", "-d")


def down(workspace: Workspace) -> None:
    """Stop and remove the containers. The volumes stay: the store is the evidence."""
    compose(workspace, "down")


def status(workspace: Workspace) -> None:
    compose(workspace, "ps")


def logs(workspace: Workspace, service: str | None = None, *, follow: bool = False) -> None:
    args = ["logs", "--tail", "200"]
    if follow:
        args.append("-f")
    if service:
        args.append(service)
    compose(workspace, *args)
