"""Bringing the compose stack up, for the end-to-end test that needs real containers.

The images a run launches from are built here, because compose builds the long-lived services and
tags them its own way while the runner is created per run from the tag the API is configured with:
a stack without it comes up healthy and refuses the first run.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
COMPOSE = ROOT / "deploy" / "compose" / "docker-compose.yml"
PROJECT = "red-teaming"
API = "http://localhost:8080"
RECEIVER = "http://localhost:8083"
RUNNER_IMAGE = "red-teaming-runner:local"

BUILD_DEADLINE = 1800.0
"""Half an hour per build: generous, and bounded, because a build that reaches for a registry and
gets no answer otherwise hangs on the network rather than failing."""


def daemon_is_up() -> bool:
    if shutil.which("docker") is None:
        return False
    return subprocess.run(("docker", "info"), capture_output=True).returncode == 0


def get(url: str, **kwargs: Any) -> Any:
    import httpx

    try:
        response = httpx.get(url, timeout=30.0, **kwargs)
        return response.json() if response.is_success else None
    except Exception:
        return None


def must_succeed(command: tuple[str, ...], environment: dict[str, str], what: str) -> None:
    """Run it, bounded, and on failure say what the builder said rather than which command."""
    try:
        done = subprocess.run(
            command, env=environment, capture_output=True, text=True, timeout=BUILD_DEADLINE
        )
    except subprocess.TimeoutExpired:
        pytest.fail(f"{what}: gave up after {BUILD_DEADLINE:.0f}s")
    if done.returncode != 0:
        pytest.fail(f"{what}:\n{done.stderr[-4000:]}")


def compose(*args: str) -> tuple[str, ...]:
    return ("docker", "compose", "-f", str(COMPOSE), "--project-name", PROJECT, *args)


def compose_logs(service: str | None = None) -> str:
    command = compose("logs", "--tail", "120", *([service] if service else []))
    return subprocess.run(command, capture_output=True, text=True).stdout[-8000:]


def bring_up(credentials: dict[str, str]) -> None:
    """Build the runner, bring the stack up with the API and the mocks built from this checkout,
    and wait for the API and the seed."""
    environment = {**os.environ, **credentials, "REDTEAM_RUNNER_IMAGE": RUNNER_IMAGE}
    must_succeed(
        (
            "docker",
            "build",
            "-q",
            "-t",
            RUNNER_IMAGE,
            "-f",
            str(ROOT / "apps/runner/Dockerfile"),
            str(ROOT),
        ),
        environment,
        f"{RUNNER_IMAGE} did not build",
    )
    must_succeed(compose("up", "-d", "--build"), environment, "the compose did not come up")
    for _ in range(90):
        if get(f"{API}/healthz") is not None and get(f"{API}/catalogues"):
            return
        time.sleep(2)
    pytest.fail(f"the API never came up seeded\n{compose_logs()}")
