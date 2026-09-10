"""The commands, against an API that answers from a script: what each one sends, keeps and exits
with."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from typer.testing import CliRunner

from redteam_cli import api as api_module
from redteam_cli import workspace
from redteam_cli.main import cli_app

ROOT = Path(__file__).resolve().parents[3]
BASELINE = ROOT / "deploy" / "seed" / "catalogues" / "assistant-baseline"


class _Api:
    """Answers each route from a table and remembers every request."""

    def __init__(self) -> None:
        self.requests: list[tuple[str, str, Any]] = []
        self.answers: dict[tuple[str, str], tuple[int, Any] | list[tuple[int, Any]]] = {}

    def __call__(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else None
        self.requests.append((request.method, request.url.path, body))
        scripted = self.answers.get((request.method, request.url.path))
        if scripted is None:
            return httpx.Response(404, json={"detail": f"no route {request.url.path}"})
        if isinstance(scripted, list):
            status, answer = scripted.pop(0) if len(scripted) > 1 else scripted[0]
        else:
            status, answer = scripted
        return httpx.Response(status, json=answer)


@pytest.fixture
def api(monkeypatch: pytest.MonkeyPatch) -> _Api:
    scripted = _Api()
    monkeypatch.setattr(api_module, "transport", lambda: httpx.MockTransport(scripted))
    return scripted


@pytest.fixture
def cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    monkeypatch.chdir(tmp_path)
    workspace.init(tmp_path, api_url="http://api", receiver_url="http://receiver")
    yield tmp_path


def _run(*args: str) -> Any:
    return CliRunner().invoke(cli_app, list(args))


def test_init_writes_the_workspace_where_it_is_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    result = _run("init", "--api-url", "http://somewhere:1")
    assert result.exit_code == 0, result.output
    assert (tmp_path / ".redteam" / "config.json").is_file()
    assert "http://somewhere:1" in result.output


def test_without_a_workspace_every_command_says_to_init(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, api: _Api
) -> None:
    monkeypatch.chdir(tmp_path)
    result = _run("run", "list")
    assert result.exit_code == 2
    assert "redteam init" in result.output


def test_catalogue_publish_sends_the_bundle_and_keeps_the_answer(cwd: Path, api: _Api) -> None:
    api.answers[("POST", "/catalogues")] = (
        201,
        {
            "name": "baseline",
            "version": 3,
            "created": True,
            "delivered": ["escalate-system-prompt"],
        },
    )

    result = _run("catalogue", "publish", "baseline", str(BASELINE))

    assert result.exit_code == 0, result.output
    [(method, path, body)] = api.requests
    assert (method, path) == ("POST", "/catalogues")
    assert body["name"] == "baseline" and body["contract"]["version"] == "v1"
    assert "published as version 3" in result.output
    kept = json.loads((cwd / ".redteam" / "catalogues" / "baseline" / "published.json").read_text())
    assert kept["version"] == 3


def test_catalogue_validate_answers_what_the_api_checked(cwd: Path, api: _Api) -> None:
    api.answers[("POST", "/catalogues:validate")] = (200, {"strategies": 11, "principles": 7})
    result = _run("catalogue", "validate", str(BASELINE))
    assert result.exit_code == 0, result.output
    assert '"strategies": 11' in result.output


def test_the_api_s_refusal_is_the_exit_and_its_words_are_the_output(cwd: Path, api: _Api) -> None:
    api.answers[("POST", "/catalogues")] = (422, {"detail": "plugin charges no such principle"})
    result = _run("catalogue", "publish", "broken", str(BASELINE))
    assert result.exit_code == 1
    assert "422" in result.output and "no such principle" in result.output


def test_an_api_that_is_down_is_its_own_exit_code(
    cwd: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("nothing is listening")

    monkeypatch.setattr(api_module, "transport", lambda: httpx.MockTransport(_down))
    result = _run("run", "list")
    assert result.exit_code == 3
    assert "redteam local status" in result.output


def test_run_start_submits_the_spec_and_follows_it_to_the_manifest(cwd: Path, api: _Api) -> None:
    spec = {"run_id": "run-1", "catalogues": ["baseline"]}
    (cwd / "spec.json").write_text(json.dumps(spec))
    api.answers[("POST", "/runs")] = (
        202,
        {"run_id": "run-1", "result_location": "runs/run-1/manifest.json", "launched": True},
    )
    attacking = {
        "phase": "attacking",
        "runner": "running",
        "closed": 3,
        "failed": 0,
        "pending": 3,
        "stalled": False,
    }
    complete = {**attacking, "phase": "complete", "runner": "succeeded", "closed": 6, "pending": 0}
    api.answers[("GET", "/runs/run-1")] = [(200, attacking), (200, complete)]
    api.answers[("GET", "/runs/run-1/result")] = (200, {"run_id": "run-1", "phase": "complete"})
    from redteam_cli import main as main_module

    main_module.POLL_SECONDS = 0.0

    result = _run("run", "start", "spec.json", "--follow")

    assert result.exit_code == 0, result.output
    assert api.requests[0] == ("POST", "/runs", spec)
    assert "attacking" in result.output and "complete" in result.output
    run_dir = cwd / ".redteam" / "runs" / "run-1"
    assert json.loads((run_dir / "accepted.json").read_text())["launched"] is True
    assert json.loads((run_dir / "manifest.json").read_text())["phase"] == "complete"


def test_a_stalled_run_stops_the_follow_and_names_the_remedy(cwd: Path, api: _Api) -> None:
    (cwd / "spec.json").write_text('{"run_id": "run-2"}')
    api.answers[("POST", "/runs")] = (202, {"run_id": "run-2", "result_location": "x"})
    api.answers[("GET", "/runs/run-2")] = (
        200,
        {
            "phase": "attacking",
            "runner": "unknown",
            "closed": 1,
            "failed": 0,
            "pending": 5,
            "stalled": True,
        },
    )

    result = _run("run", "start", "spec.json", "--follow")

    assert result.exit_code == 4
    assert "redteam run resume run-2" in result.output


def test_a_failed_run_is_a_non_zero_exit_after_the_status_is_kept(cwd: Path, api: _Api) -> None:
    (cwd / "spec.json").write_text('{"run_id": "run-3"}')
    api.answers[("POST", "/runs")] = (202, {"run_id": "run-3", "result_location": "x"})
    api.answers[("GET", "/runs/run-3")] = (
        200,
        {
            "phase": "failed",
            "runner": "failed",
            "closed": 1,
            "failed": 0,
            "pending": 5,
            "stalled": False,
        },
    )

    result = _run("run", "start", "spec.json", "--follow")

    assert result.exit_code == 1
    assert json.loads((cwd / ".redteam/runs/run-3/status.json").read_text())["phase"] == "failed"


def test_status_result_list_and_resume_read_and_relaunch(cwd: Path, api: _Api) -> None:
    api.answers[("GET", "/runs")] = (200, {"runs": ["run-a", "run-b"]})
    api.answers[("GET", "/runs/run-a")] = (200, {"phase": "complete", "stalled": False})
    api.answers[("GET", "/runs/run-a/result")] = (200, {"n_total_traces": 6})
    api.answers[("POST", "/runs/run-a:resume")] = (202, {"launched": True, "runner": "running"})

    assert _run("run", "list").output.split() == ["run-a", "run-b"]
    assert '"phase": "complete"' in _run("run", "status", "run-a").output
    assert '"n_total_traces": 6' in _run("run", "result", "run-a").output
    assert '"launched": true' in _run("run", "resume", "run-a").output
    assert json.loads((cwd / ".redteam/runs/run-a/manifest.json").read_text()) == {
        "n_total_traces": 6
    }


def test_prior_publish_reads_lines_and_sends_them(cwd: Path, api: _Api) -> None:
    (cwd / "prior.txt").write_text("hola\nque cubre?\n")
    api.answers[("POST", "/priors")] = (201, {"name": "support", "version": 1, "size": 2})

    result = _run("prior", "publish", "support", "prior.txt")

    assert result.exit_code == 0, result.output
    assert api.requests[0] == (
        "POST",
        "/priors",
        {"name": "support", "phrasings": ["hola", "que cubre?"]},
    )


def test_receiver_export_keeps_what_the_receiver_holds(cwd: Path, api: _Api) -> None:
    api.answers[("GET", "/received")] = (200, [{"run_id": "run-a", "phase": "complete"}])

    result = _run("receiver", "export", "run-a")

    assert result.exit_code == 0, result.output
    assert api.requests[0][0:2] == ("GET", "/received")
    kept = json.loads((cwd / ".redteam/runs/run-a/delivery.json").read_text())
    assert kept == [{"run_id": "run-a", "phase": "complete"}]

    api.answers[("GET", "/received")] = (200, [])
    assert _run("receiver", "export", "run-b").exit_code == 1


def test_the_compose_file_ships_with_the_command_line() -> None:
    from redteam_cli import local

    found = local.compose_file()
    assert found.name == "docker-compose.yml"
    assert local.repository_root() == ROOT
