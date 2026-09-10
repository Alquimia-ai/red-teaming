"""`redteam`: the command line.

redteam init [--api-url] [--receiver-url]      the workspace: .redteam/
redteam local up [--build] | down | status | logs
redteam catalogue validate <dir> | publish <name> <dir> | list
redteam prior publish <name> <file>
redteam run validate <spec> | start <spec> [--follow] [--deadline] | status | result | list |
            resume <run_id>
redteam receiver export <run_id>               what the local receiver was delivered
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any

import typer

from redteam_cli import api as api_module
from redteam_cli import bundle, local, workspace

cli_app = typer.Typer(add_completion=False, no_args_is_help=True, help="Govern red-teaming runs.")
local_app = typer.Typer(no_args_is_help=True, help="The local stack, through docker compose.")
catalogue_app = typer.Typer(no_args_is_help=True, help="Catalogue bundles.")
prior_app = typer.Typer(no_args_is_help=True, help="Natural-query priors.")
run_app = typer.Typer(no_args_is_help=True, help="Runs.")
receiver_app = typer.Typer(no_args_is_help=True, help="The local webhook receiver.")
cli_app.add_typer(local_app, name="local")
cli_app.add_typer(catalogue_app, name="catalogue")
cli_app.add_typer(prior_app, name="prior")
cli_app.add_typer(run_app, name="run")
cli_app.add_typer(receiver_app, name="receiver")

TERMINAL = frozenset({"complete", "failed"})
POLL_SECONDS = 5.0


def _say(payload: Any) -> None:
    typer.echo(json.dumps(payload, indent=2, sort_keys=True))


def _fail(message: str, code: int = 1) -> None:
    typer.echo(message, err=True)
    raise typer.Exit(code=code)


def _workspace() -> workspace.Workspace:
    try:
        return workspace.load()
    except workspace.NoWorkspace as missing:
        _fail(str(missing), code=2)
        raise AssertionError from missing


def _api(ws: workspace.Workspace) -> api_module.Api:
    return api_module.Api(ws.config.api_url)


def _asking(action: Any) -> Any:
    """Run one request and turn the API's refusal into an exit code and its own words."""
    try:
        return action()
    except api_module.ApiError as refused:
        _fail(f"the API refused ({refused.status}): {refused.detail}")
    except api_module.Unreachable as down:
        _fail(str(down), code=3)


# ---- init and local -----------------------------------------------------------------------------


@cli_app.command()
def init(
    api_url: str = typer.Option(workspace.DEFAULT_API_URL, help="Where the API answers."),
    receiver_url: str = typer.Option(
        workspace.DEFAULT_RECEIVER_URL, help="Where the local webhook receiver answers."
    ),
) -> None:
    """Create the workspace here: .redteam/ with its configuration and credentials file."""
    created = workspace.init(Path.cwd(), api_url=api_url, receiver_url=receiver_url)
    typer.echo(f"workspace at {created.root}")
    typer.echo(f"  api: {created.config.api_url}")
    typer.echo(f"  credentials: {created.env_file} (edit it before `redteam local up`)")


@local_app.command("up")
def local_up(
    build: bool = typer.Option(
        False, help="Build the images from this checkout instead of pulling."
    ),
) -> None:
    """Bring the local stack up: minio, the API, the seed, the receiver and the mock target."""
    ws = _workspace()
    try:
        local.up(ws, build=build)
    except (local.NoDocker, FileNotFoundError) as refused:
        _fail(str(refused), code=3)
    typer.echo(f"stack up; api at {ws.config.api_url}")


@local_app.command("down")
def local_down() -> None:
    """Stop the local stack. Volumes stay: every run the store holds survives."""
    ws = _workspace()
    try:
        local.down(ws)
    except local.NoDocker as refused:
        _fail(str(refused), code=3)


@local_app.command("status")
def local_status() -> None:
    ws = _workspace()
    try:
        local.status(ws)
    except local.NoDocker as refused:
        _fail(str(refused), code=3)


@local_app.command("logs")
def local_logs(
    service: str | None = typer.Argument(None), follow: bool = typer.Option(False, "--follow", "-f")
) -> None:
    ws = _workspace()
    try:
        local.logs(ws, service, follow=follow)
    except local.NoDocker as refused:
        _fail(str(refused), code=3)


# ---- catalogues and priors ----------------------------------------------------------------------


def _bundle_body(directory: Path, name: str) -> dict[str, Any]:
    try:
        return bundle.read_bundle(directory, name)
    except (bundle.BundleIncomplete, ValueError) as malformed:
        _fail(str(malformed))
        raise AssertionError from malformed


@catalogue_app.command("validate")
def catalogue_validate(directory: Path = typer.Argument(..., exists=True, file_okay=False)) -> None:
    """Run every check publishing runs, and write nothing."""
    ws = _workspace()
    checked = _asking(lambda: _api(ws).validate_bundle(_bundle_body(directory, directory.name)))
    _say(checked)


@catalogue_app.command("publish")
def catalogue_publish(
    name: str, directory: Path = typer.Argument(..., exists=True, file_okay=False)
) -> None:
    """Publish the bundle as the next version of `name`, and keep what the API answered."""
    ws = _workspace()
    published = _asking(lambda: _api(ws).publish_bundle(_bundle_body(directory, name)))
    kept = ws.catalogues / name
    kept.mkdir(parents=True, exist_ok=True)
    (kept / "published.json").write_text(json.dumps(published, indent=2, sort_keys=True) + "\n")
    verb = "published" if published.get("created") else "already published"
    typer.echo(f"{name}: {verb} as version {published['version']} ({kept / 'published.json'})")


@catalogue_app.command("list")
def catalogue_list() -> None:
    ws = _workspace()
    _say(_asking(lambda: _api(ws).catalogues()))


@prior_app.command("publish")
def prior_publish(name: str, file: Path = typer.Argument(..., exists=True, dir_okay=False)) -> None:
    """Publish a natural-query prior: a JSON list, or one phrasing per line."""
    ws = _workspace()
    try:
        phrasings = bundle.read_phrasings(file)
    except ValueError as malformed:
        _fail(str(malformed))
        raise AssertionError from malformed
    published = _asking(lambda: _api(ws).publish_prior(name, phrasings))
    _say(published)


# ---- runs ---------------------------------------------------------------------------------------


def _spec(path: Path) -> dict[str, Any]:
    try:
        return bundle.read_spec(path)
    except ValueError as malformed:
        _fail(str(malformed))
        raise AssertionError from malformed


@run_app.command("validate")
def run_validate(spec: Path = typer.Argument(..., exists=True, dir_okay=False)) -> None:
    """The gate alone: what `start` would freeze, with nothing written."""
    ws = _workspace()
    _say(_asking(lambda: _api(ws).validate_run(_spec(spec))))


@run_app.command("start")
def run_start(
    spec: Path = typer.Argument(..., exists=True, dir_okay=False),
    follow: bool = typer.Option(False, help="Poll the status until the run closes or fails."),
    deadline: float = typer.Option(
        1800.0, help="How long --follow waits, in seconds, before giving up."
    ),
) -> None:
    """Submit the spec. The API validates, freezes it and launches a runner."""
    ws = _workspace()
    body = _spec(spec)
    accepted = _asking(lambda: _api(ws).start_run(body))
    run_id = str(accepted["run_id"])
    ws.keep(run_id, "accepted.json", accepted)
    typer.echo(f"{run_id}: accepted; manifest will appear at {accepted['result_location']}")
    if follow:
        _follow(ws, run_id, deadline)


def _follow(ws: workspace.Workspace, run_id: str, deadline: float) -> None:
    api = _api(ws)
    expires = time.monotonic() + deadline
    last = ""
    while True:
        status = _asking(lambda: api.status(run_id))
        line = (
            f"{status['phase']} runner={status['runner']} closed={status['closed']} "
            f"failed={status['failed']} pending={status['pending']}"
            + (" STALLED" if status.get("stalled") else "")
        )
        if line != last:
            typer.echo(f"{run_id}: {line}")
            last = line
        if status["phase"] in TERMINAL:
            ws.keep(run_id, "status.json", status)
            if status["phase"] == "complete":
                ws.keep(run_id, "manifest.json", _asking(lambda: api.result(run_id)))
            else:
                raise typer.Exit(code=1)
            return
        if status.get("stalled"):
            _fail(
                f"{run_id} is stalled: the store says {status['phase']} and the platform says the "
                f"runner is {status['runner']}. `redteam run resume {run_id}` relaunches it.",
                code=4,
            )
        if time.monotonic() >= expires:
            _fail(f"{run_id} is still {status['phase']} after {deadline:g}s; giving up", code=5)
        time.sleep(POLL_SECONDS)


@run_app.command("status")
def run_status(run_id: str) -> None:
    ws = _workspace()
    status = _asking(lambda: _api(ws).status(run_id))
    ws.keep(run_id, "status.json", status)
    _say(status)


@run_app.command("result")
def run_result(run_id: str) -> None:
    """The manifest, kept as .redteam/runs/<run_id>/manifest.json."""
    ws = _workspace()
    manifest = _asking(lambda: _api(ws).result(run_id))
    kept = ws.keep(run_id, "manifest.json", manifest)
    _say(manifest)
    typer.echo(f"kept at {kept}", err=True)


@run_app.command("list")
def run_list() -> None:
    ws = _workspace()
    for run_id in _asking(lambda: _api(ws).runs()):
        typer.echo(run_id)


@run_app.command("resume")
def run_resume(run_id: str) -> None:
    """Launch a runner for the run again; it resumes from what the store already holds."""
    ws = _workspace()
    _say(_asking(lambda: _api(ws).resume(run_id)))


# ---- receiver -----------------------------------------------------------------------------------


@receiver_app.command("export")
def receiver_export(run_id: str) -> None:
    """What the local receiver was delivered for the run, kept as delivery.json."""
    ws = _workspace()
    receiver = api_module.Receiver(ws.config.receiver_url)
    deliveries = _asking(lambda: receiver.received(run_id))
    if not deliveries:
        _fail(f"the receiver holds no delivery for {run_id}")
    kept = ws.keep(run_id, "delivery.json", deliveries)
    _say(deliveries)
    typer.echo(f"kept at {kept}", err=True)


def cli() -> None:
    cli_app()


if __name__ == "__main__":
    sys.exit(cli_app())
