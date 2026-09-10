"""The whole stack in containers, driven by the command line. Marked `docker`: it needs a daemon.

The in-process end-to-end already exercises the platform, so what this adds is everything that
cannot fail in process: whether the images build, whether the API can reach the Docker socket,
whether the runner container joins the network and finds minio and the target by name, whether the
mock target speaks the runtime's protocol the adapter expects, whether the receiver keeps what it
acknowledges, and whether the command line's grammar matches the API's.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

from tests.e2e.stack import API, RECEIVER, ROOT, bring_up, compose_logs, daemon_is_up

pytestmark = pytest.mark.docker

STATIC_STRATEGIES = ["ask-identity", "ask-system-prompt", "act-for-another", "refuse-escalation"]
"""The standing strategies that are one turn each. The conducted one needs an attacker model, which
this stack does not carry; narrowing past it is what a run with no model does."""


@pytest.fixture(scope="module")
def stack() -> None:
    if not daemon_is_up():
        pytest.skip("no docker daemon")
    bring_up({"TARGET_KEY": "mock-target-checks-nothing"})


def _redteam(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "redteam_cli.main", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONPATH": str(ROOT / "apps" / "cli" / "src")},
        timeout=1800,
    )


def test_the_command_line_takes_a_run_from_the_workspace_to_the_delivery(
    stack: None, tmp_path: Path
) -> None:
    run_id = f"redteam-run-compose-{uuid.uuid4().hex[:8]}"
    spec = {
        "run_id": run_id,
        "kb_ref": None,
        "catalogues": ["assistant-baseline"],
        "plugins": [],
        "strategies": STATIC_STRATEGIES,
        "connector": {
            "kind": "alquimia",
            "endpoint": "http://mock-target:8080",
            "secret_ref": "TARGET_KEY",
            "options": {"assistant_id": "mock", "agentspace_id": "default"},
        },
        "judge": {"model": "stand-in"},
        "context": {"language": "en", "domain": "an assistant under test"},
        "replicas": 2,
        "webhook_url": "http://receiver:8080/hook",
    }
    (tmp_path / "spec.json").write_text(json.dumps(spec))

    init = _redteam(tmp_path, "init", "--api-url", API, "--receiver-url", RECEIVER)
    assert init.returncode == 0, init.stderr

    published = _redteam(
        tmp_path,
        "catalogue",
        "publish",
        "assistant-baseline",
        str(ROOT / "deploy/seed/catalogues/assistant-baseline"),
    )
    assert published.returncode == 0, published.stderr
    assert "already published" in published.stdout, "the seed published it when the stack came up"

    started = _redteam(tmp_path, "run", "start", "spec.json", "--follow", "--deadline", "900")
    assert started.returncode == 0, f"{started.stdout}\n{started.stderr}\n{compose_logs('api')}"
    assert "complete" in started.stdout

    manifest = json.loads((tmp_path / ".redteam" / "runs" / run_id / "manifest.json").read_text())
    assert manifest["phase"] == "complete"
    assert manifest["coverage"]["total"]["planned"] == (len(STATIC_STRATEGIES) + 1) * 2
    assert manifest["coverage"]["total"]["closed"] == manifest["coverage"]["total"]["planned"]
    assert manifest["components"]["target"] == "alquimia"
    assert manifest["profile"] and manifest["dataset"]

    exported = _redteam(tmp_path, "receiver", "export", run_id)
    assert exported.returncode == 0, f"{exported.stderr}\n{compose_logs('receiver')}"
    [delivery] = json.loads((tmp_path / ".redteam" / "runs" / run_id / "delivery.json").read_text())
    assert (
        delivery["phase"] == "complete" and delivery["manifest"] == f"runs/{run_id}/manifest.json"
    )

    again = _redteam(tmp_path, "run", "start", "spec.json", "--follow", "--deadline", "300")
    assert again.returncode == 0, again.stderr
    listed = _redteam(tmp_path, "run", "list")
    assert run_id in listed.stdout.split()
    target_calls = compose_logs("mock-target").count("POST /event/infer")
    assert target_calls == manifest["n_total_traces"], "a closed run is never attacked again"
