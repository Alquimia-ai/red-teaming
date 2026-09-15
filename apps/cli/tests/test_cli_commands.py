"""The commands, against an API that answers from a script: what each one sends, keeps, prints and
exits with."""

from __future__ import annotations

import io
import json
import subprocess
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Any

import httpx
import pytest
from rich.console import Console

from redteam_cli import api as api_module
from redteam_cli import main as main_module
from redteam_cli import workspace
from redteam_cli.main import DEADLINE, NO_WORKSPACE, OK, REFUSED, STALLED, UNREACHABLE, main

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


class _Run:
    """`main` with both consoles captured, so a test reads what a person would."""

    def __init__(self) -> None:
        self.out = io.StringIO()
        self.err = io.StringIO()

    def __call__(self, *args: str) -> int:
        return main(
            list(args),
            out=Console(file=self.out, width=200, force_terminal=False, no_color=True),
            err=Console(file=self.err, width=200, force_terminal=False, no_color=True),
        )

    @property
    def stdout(self) -> str:
        return self.out.getvalue()

    @property
    def stderr(self) -> str:
        return self.err.getvalue()


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


@pytest.fixture
def run() -> _Run:
    return _Run()


def _status(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "phase": "attacking",
        "runner": "running",
        "closed": 3,
        "failed": 0,
        "pending": 3,
        "planned": 6,
        "stalled": False,
    }
    base.update(overrides)
    return base


def test_init_writes_the_workspace_where_it_is_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, run: _Run
) -> None:
    monkeypatch.chdir(tmp_path)
    assert run("init", "--api-url", "http://somewhere:1") == OK
    assert (tmp_path / ".redteam" / "config.json").is_file()
    assert "http://somewhere:1" in run.stdout


def test_without_a_workspace_every_command_says_to_init(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, api: _Api, run: _Run
) -> None:
    monkeypatch.chdir(tmp_path)
    assert run("run", "list") == NO_WORKSPACE
    assert "redteam init" in run.stderr


def test_no_command_is_the_usage_and_a_bad_command_is_a_parse_error(run: _Run) -> None:
    assert main([]) == 2
    assert main(["nonsense"]) == 2


def test_catalogue_publish_sends_the_bundle_and_keeps_the_answer(
    cwd: Path, api: _Api, run: _Run
) -> None:
    api.answers[("POST", "/catalogues")] = (
        201,
        {
            "name": "assistant-baseline",
            "version": 3,
            "created": True,
            "delivered": ["escalate-system-prompt"],
        },
    )

    assert run("catalogue", "publish", str(BASELINE.with_suffix(".json"))) == OK

    [(method, path, body)] = api.requests
    assert (method, path) == ("POST", "/catalogues")
    assert body["name"] == "assistant-baseline" and body["contract"]["version"] == "v1"
    assert "published as version 3" in run.stdout
    kept = json.loads(
        (cwd / ".redteam" / "catalogues" / "assistant-baseline" / "published.json").read_text()
    )
    assert kept["version"] == 3


def test_catalogue_validate_renders_a_table_or_json(cwd: Path, api: _Api, run: _Run) -> None:
    api.answers[("POST", "/catalogues:validate")] = (
        200,
        {
            "strategies": 11,
            "principles": 7,
            "needs_base": ["ask-about-fake-product"],
            "delivered": [],
        },
    )

    assert run("catalogue", "validate", str(BASELINE.with_suffix(".json"))) == OK
    assert "every check passed" in run.stdout and "11" in run.stdout

    as_json = _Run()
    assert as_json("--json", "catalogue", "validate", str(BASELINE.with_suffix(".json"))) == OK
    assert json.loads(as_json.stdout)["strategies"] == 11


def test_catalogue_list_is_a_table(cwd: Path, api: _Api, run: _Run) -> None:
    api.answers[("GET", "/catalogues")] = (200, {"baseline": [1, 2], "siblings": [1]})
    assert run("catalogue", "list") == OK
    assert "baseline" in run.stdout and "1, 2" in run.stdout


def test_the_api_s_refusal_is_the_exit_and_its_words_are_the_output(
    cwd: Path, api: _Api, run: _Run
) -> None:
    api.answers[("POST", "/catalogues")] = (422, {"detail": "plugin charges no such principle"})
    assert run("catalogue", "publish", str(BASELINE.with_suffix(".json"))) == REFUSED
    assert "422" in run.stderr and "no such principle" in run.stderr


def test_an_api_that_is_down_is_its_own_exit_code(
    cwd: Path, monkeypatch: pytest.MonkeyPatch, run: _Run
) -> None:
    def _down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("nothing is listening")

    monkeypatch.setattr(api_module, "transport", lambda: httpx.MockTransport(_down))
    assert run("run", "list") == UNREACHABLE
    assert "redteam local status" in run.stderr


def test_run_start_submits_the_spec_and_follows_it_to_the_manifest(
    cwd: Path, api: _Api, run: _Run, monkeypatch: pytest.MonkeyPatch
) -> None:
    spec = {"run_id": "run-1", "catalogues": ["baseline"]}
    (cwd / "spec.json").write_text(json.dumps(spec))
    api.answers[("POST", "/runs")] = (
        202,
        {"run_id": "run-1", "result_location": "runs/run-1/manifest.json", "launched": True},
    )
    api.answers[("GET", "/runs/run-1")] = [
        (200, _status()),
        (200, _status(phase="complete", runner="succeeded", closed=6, pending=0)),
    ]
    api.answers[("GET", "/runs/run-1/result")] = (
        200,
        {
            "run_id": "run-1",
            "phase": "complete",
            "n_total_traces": 6,
            "dataset": "runs/run-1/dataset.json",
            "coverage": {
                "total": {"planned": 6, "closed": 6, "failed": 0},
                "by_plugin": {"disclosure": {"planned": 2, "closed": 2, "failed": 0}},
                "by_strategy": {},
            },
            "components": {"target": "alquimia"},
        },
    )
    monkeypatch.setattr(main_module, "POLL_SECONDS", 0.0)

    assert run("run", "start", "spec.json", "--follow") == OK

    assert api.requests[0] == ("POST", "/runs", spec)
    assert "attacking" in run.stdout and "complete" in run.stdout
    assert "disclosure" in run.stdout, "the manifest's coverage is rendered when the run closes"
    run_dir = cwd / ".redteam" / "runs" / "run-1"
    assert json.loads((run_dir / "accepted.json").read_text())["launched"] is True
    assert json.loads((run_dir / "manifest.json").read_text())["phase"] == "complete"


def test_a_stalled_run_stops_the_follow_and_names_the_remedy(
    cwd: Path, api: _Api, run: _Run
) -> None:
    (cwd / "spec.json").write_text('{"run_id": "run-2"}')
    api.answers[("POST", "/runs")] = (202, {"run_id": "run-2", "result_location": "x"})
    api.answers[("GET", "/runs/run-2")] = (200, _status(runner="unknown", stalled=True))

    assert run("run", "start", "spec.json", "--follow") == STALLED
    assert "redteam run resume run-2" in run.stderr


def test_a_failed_run_is_a_non_zero_exit_after_the_status_is_kept(
    cwd: Path, api: _Api, run: _Run
) -> None:
    (cwd / "spec.json").write_text('{"run_id": "run-3"}')
    api.answers[("POST", "/runs")] = (202, {"run_id": "run-3", "result_location": "x"})
    api.answers[("GET", "/runs/run-3")] = (200, _status(phase="failed", runner="failed"))

    assert run("run", "start", "spec.json", "--follow") == REFUSED
    assert json.loads((cwd / ".redteam/runs/run-3/status.json").read_text())["phase"] == "failed"


def test_a_deadline_that_passes_is_its_own_exit(
    cwd: Path, api: _Api, run: _Run, monkeypatch: pytest.MonkeyPatch
) -> None:
    (cwd / "spec.json").write_text('{"run_id": "run-4"}')
    api.answers[("POST", "/runs")] = (202, {"run_id": "run-4", "result_location": "x"})
    api.answers[("GET", "/runs/run-4")] = (200, _status())
    monkeypatch.setattr(main_module, "POLL_SECONDS", 0.0)

    assert run("run", "start", "spec.json", "--follow", "--deadline", "0") == DEADLINE
    assert "giving up" in run.stderr


def test_status_result_list_and_resume_read_and_relaunch(cwd: Path, api: _Api) -> None:
    api.answers[("GET", "/runs")] = (200, {"runs": ["run-a", "run-b"]})
    api.answers[("GET", "/runs/run-a")] = (200, _status(phase="complete", runner="succeeded"))
    api.answers[("GET", "/runs/run-a/result")] = (
        200,
        {"run_id": "run-a", "phase": "complete", "n_total_traces": 6, "coverage": {}},
    )
    api.answers[("POST", "/runs/run-a:resume")] = (202, {"launched": True, "runner": "running"})

    listed = _Run()
    assert listed("run", "list") == OK and listed.stdout.split() == ["run-a", "run-b"]
    status = _Run()
    assert status("run", "status", "run-a") == OK and "complete" in status.stdout
    as_json = _Run()
    assert as_json("--json", "run", "status", "run-a") == OK
    assert json.loads(as_json.stdout)["phase"] == "complete"
    result = _Run()
    assert result("run", "result", "run-a") == OK and "manifest" in result.stdout
    resumed = _Run()
    assert resumed("run", "resume", "run-a") == OK and "runner launched" in resumed.stdout
    assert (
        json.loads((cwd / ".redteam/runs/run-a/manifest.json").read_text())["n_total_traces"] == 6
    )


def test_prior_publish_reads_lines_and_sends_them(cwd: Path, api: _Api, run: _Run) -> None:
    (cwd / "prior.txt").write_text("hola\nque cubre?\n")
    api.answers[("POST", "/priors")] = (201, {"name": "support", "version": 1, "size": 2})

    assert run("prior", "publish", "support", "prior.txt") == OK
    assert api.requests[0] == (
        "POST",
        "/priors",
        {"name": "support", "phrasings": ["hola", "que cubre?"]},
    )
    assert "2 phrasings" in run.stdout


def test_receiver_export_keeps_what_the_receiver_holds(cwd: Path, api: _Api, run: _Run) -> None:
    api.answers[("GET", "/received")] = (200, [{"run_id": "run-a", "phase": "complete"}])

    assert run("receiver", "export", "run-a") == OK
    assert api.requests[0][0:2] == ("GET", "/received")
    kept = json.loads((cwd / ".redteam/runs/run-a/delivery.json").read_text())
    assert kept == [{"run_id": "run-a", "phase": "complete"}]

    api.answers[("GET", "/received")] = (200, [])
    assert _Run()("receiver", "export", "run-b") == REFUSED


def test_the_compose_file_ships_with_the_command_line() -> None:
    from redteam_cli import local

    found = local.compose_file()
    assert found.name == "docker-compose.yml"
    assert local.repository_root() == ROOT


def test_a_stack_that_will_not_come_up_is_a_message_and_an_exit_code(
    cwd: Path, run: _Run, monkeypatch: pytest.MonkeyPatch
) -> None:
    """docker compose prints its own diagnosis -- an image it cannot pull, a port already bound.
    The command line's job is to end there, with a code, not to raise through subprocess."""
    monkeypatch.setattr("redteam_cli.local.shutil.which", lambda _: "/usr/bin/docker")
    monkeypatch.setattr(
        "redteam_cli.local.subprocess.run",
        lambda *a, **k: subprocess.CompletedProcess(args=a[0] if a else [], returncode=1),
    )
    assert run("local", "up") == UNREACHABLE
    assert "docker compose -f" in run.stderr and "exited 1" in run.stderr
    assert "Traceback" not in run.stderr


def test_the_stack_pulls_minio_from_where_minio_publishes() -> None:
    """Docker Hub answers an anonymous pull of `minio/minio` with `pull access denied`, so a stack
    that named it could not come up on a clean machine. The chart and the compose file agree."""
    compose = (ROOT / "deploy/compose/docker-compose.yml").read_text()
    values = (ROOT / "deploy/charts/red-teaming-stack/values.yaml").read_text()
    for text, where in ((compose, "the compose file"), (values, "the chart's values")):
        for line in text.splitlines():
            named = line.split(":", 1)[1].strip() if ":" in line else ""
            if named.startswith(("minio/minio", "minio/mc")):
                raise AssertionError(f"{where} pulls {named} from Docker Hub, which denies it")
        assert "quay.io/minio/minio" in text and "quay.io/minio/mc" in text, where


def test_the_command_line_carries_no_click(cwd: Path) -> None:
    """Parsed with the standard library and rendered with rich; a click or typer import is a
    dependency somebody added back."""
    import tomllib

    deps: Sequence[str] = tomllib.loads((ROOT / "apps/cli/pyproject.toml").read_text())["project"][
        "dependencies"
    ]
    assert not any(d.startswith(("typer", "click")) for d in deps)
    assert any(d.startswith("rich") for d in deps)
