"""The runner's command line: `redteam-runner run <run_id>`.

One subcommand, and the grammar is pinned on purpose: the dispatchers hand the image `["run",
<id>]`, so a change here is a container that starts and dies.
"""

from __future__ import annotations

import sys

import typer

cli_app = typer.Typer(add_completion=False, help="Run one red-teaming run to completion.")


@cli_app.callback()
def _root() -> None:
    """Keep `run` an explicit subcommand.

    Typer promotes a lone command to the default one, which silently changes the argument
    grammar: `redteam-runner run <id>` then parses "run" as the run id and the id as a stray extra.
    A callback pins the grammar, which matters because every dispatcher's command is written
    against it.
    """


@cli_app.command()
def run(run_id: str, dry_run: bool = False) -> None:
    """Execute the run named by `run_id`, resuming whatever is already in the store."""
    from redteam_contracts.manifest import RunPhase
    from redteam_contracts.run_id import check
    from redteam_runner.pipeline import execute
    from redteam_settings.config import load
    from redteam_store import layout
    from redteam_store.interface import ObjectNotFound

    try:
        check(run_id)
    except ValueError as refused:
        # The gate already refused this shape, so reaching here means a launch that bypassed the
        # API. Said plainly and exited as "nothing to resume" rather than as a failed attempt.
        typer.echo(str(refused))
        raise typer.Exit(code=2) from None

    settings = load()
    typer.echo(
        f"run {run_id}: store={settings.store_backend.value} "
        f"secrets={settings.secrets_backend.value}"
    )

    try:
        outcome = execute(run_id, settings=settings, dry_run=dry_run)
    except ObjectNotFound:
        typer.echo(f"no frozen spec at {layout.spec(run_id)}; the API has not accepted this run")
        raise typer.Exit(code=2) from None

    typer.echo(
        f"run {run_id}: {outcome.phase.value}, {outcome.n_traces} traces closed, "
        f"{outcome.resumed} of them before this attempt"
        + (f"; webhook {type(outcome.delivery).__name__}" if outcome.delivery else "")
    )
    if outcome.phase is RunPhase.FAILED:
        # Non-zero so the platform's retry policy -- a Job's backoffLimit -- sees a failed execution
        # and relaunches. The relaunch resumes from the difference; nothing closed is re-executed.
        # Exiting 0 here would report a failed run as a successful job, and no retry would come.
        raise typer.Exit(code=1)


def cli() -> None:
    cli_app()


if __name__ == "__main__":
    sys.exit(cli_app())
