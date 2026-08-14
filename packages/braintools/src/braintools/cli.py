"""The ``braintools`` command-line entry point.

Curates the Boltzmann brain through vitruvio, and exports/ingests the data artifacts
that cross the boundary to the red-teaming app (knowledge out, findings in). Every data
command emits the ``data`` from vitruvio's JSON envelope — the brain returns evidence,
never prose. Failures and warnings are surfaced on stderr.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Any

import typer

from . import config
from .vitruvio import Result, Vitruvio, VitruvioError

app = typer.Typer(
    name="braintools",
    help="Curate the red-teaming Boltzmann brain (wraps vitruvio).",
    no_args_is_help=True,
)


def _emit(result: Result) -> None:
    for w in result.warnings:
        typer.echo(f"warning: {w}", err=True)
    typer.echo(json.dumps(result.data, indent=2, ensure_ascii=False, default=str))


def _brain() -> Vitruvio:
    return Vitruvio()


def _guard(fn) -> Any:
    try:
        return fn()
    except VitruvioError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc
    except FileNotFoundError as exc:
        typer.echo(
            f"vitruvio not found ({config.vitruvio_bin()!r}). Install it with the "
            f"official script (see README), or set {config.VITRUVIO_BIN_ENV}.",
            err=True,
        )
        raise typer.Exit(code=127) from exc


@app.command("init")
def init(
    actor: Annotated[
        str | None, typer.Option(help="Actor id written into the new vitruvio.toml.")
    ] = None,
    actor_kind: Annotated[
        str | None, typer.Option(help="human, agent, service or pipeline.")
    ] = None,
) -> None:
    """Create the brain at $BRAINTOOLS_BRAIN_DIR (default ./brain)."""
    _emit(_guard(lambda: _brain().init(actor=actor, actor_kind=actor_kind)))


@app.command("ingest")
def ingest(
    source: Annotated[Path, typer.Argument(help="The file to ingest.")],
    proposer: Annotated[
        str | None,
        typer.Option(help="structure (default), anthropic[:model], or openai[:model]."),
    ] = None,
    media_type: Annotated[
        str | None, typer.Option("--media-type", "-m", help="e.g. application/pdf.")
    ] = None,
    subject: Annotated[
        str | None, typer.Option(help="Tag every proposal with this subject.")
    ] = None,
    origin: Annotated[
        str | None, typer.Option(help="Where the source came from. Defaults to the path.")
    ] = None,
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Propose and validate, commit nothing.")
    ] = False,
) -> None:
    """Ingest one document into the brain (vitruvio ingest run)."""
    _emit(
        _guard(
            lambda: _brain().ingest(
                source, dry_run=dry_run, proposer=proposer,
                media_type=media_type, subject=subject, origin=origin,
            )
        )
    )


@app.command("index")
def index() -> None:
    """Build or refresh the brain's search indices (vitruvio index build)."""
    _emit(_guard(lambda: _brain().index()))


@app.command("search")
def search(
    text: Annotated[str, typer.Argument(help="What to look for.")],
    limit: Annotated[int | None, typer.Option("--limit", "-n", help="Max matches.")] = None,
    memory_type: Annotated[
        list[str] | None,
        typer.Option("--memory-type", "-m", help="Restrict to these modules. Repeatable."),
    ] = None,
    mode: Annotated[
        str | None, typer.Option(help="auto, exact, lexical, semantic or associative.")
    ] = None,
    content: Annotated[
        bool, typer.Option("--content", help="Print each block's full payload.")
    ] = False,
) -> None:
    """Retrieve verified evidence from the brain (vitruvio search)."""
    _emit(
        _guard(
            lambda: _brain().search(
                text, limit=limit, memory_types=memory_type, mode=mode, content=content
            )
        )
    )


@app.command("browse")
def browse(
    memory_type: Annotated[
        str | None, typer.Option("--memory-type", "-m", help="Which module to open on.")
    ] = None,
) -> None:
    """Open the interactive brain explorer (vitruvio browse)."""
    code = _guard(lambda: _brain().browse(memory_type=memory_type))
    raise typer.Exit(code=code)


# -- the data boundary with the red-teaming app --------------------------------

@app.command("ingest-findings")
def ingest_findings(
    findings: Annotated[
        Path, typer.Argument(help="A findings artifact emitted by `redteam roast`.")
    ],
    subject: Annotated[
        str, typer.Option(help="Subject to tag the findings under.")
    ] = "red-teaming-findings",
    proposer: Annotated[str, typer.Option()] = "structure",
) -> None:
    """Ingest a red-teaming findings artifact back into the brain as evidence.

    The app writes findings to a file/volume knowing nothing about the brain; this is
    the brain side of that boundary.
    """
    _emit(
        _guard(
            lambda: _brain().ingest(findings, proposer=proposer, subject=subject)
        )
    )
