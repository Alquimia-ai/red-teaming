"""The ``redteam`` command-line entry point (the deployable app).

The app reads a knowledge bundle and writes findings through ``redteam.ports`` — it
never touches the brain. ``check`` validates the input boundary; ``roast`` (roadmap)
runs the RoastMe arc and writes the findings artifact.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Annotated

import typer

from . import config
from .ports import FileKnowledgeSource

app = typer.Typer(
    name="redteam",
    help="Red teaming for Alquimia agents. Reads a knowledge bundle, emits findings.",
    no_args_is_help=True,
)


@app.command("check")
def check(
    knowledge_path: Annotated[
        str | None,
        typer.Option("--knowledge", help="Knowledge bundle JSON (env REDTEAM_KNOWLEDGE_PATH)."),
    ] = None,
) -> None:
    """Validate the knowledge input boundary and print a summary."""
    path = Path(knowledge_path) if knowledge_path else config.knowledge_path()
    try:
        bundle = FileKnowledgeSource(path).load()
    except FileNotFoundError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc
    summary = {
        "knowledge_path": str(path),
        "documents": len(bundle.documents),
        "has_catalogue": bundle.catalogue is not None,
        "has_contract": bundle.contract is not None,
    }
    typer.echo(json.dumps(summary, indent=2, ensure_ascii=False))


@app.command("roast")
def roast() -> None:
    """[roadmap] Run the RoastMe arc against the Alquimia agent, then write findings.

    Requires the `roast` extra:  uv sync --extra roast

    Reads the knowledge bundle via redteam.ports.FileKnowledgeSource, drives gaussia
    RoastMe (contract + catalogue → probes → Profiler → Exploiter) against the agent
    (redteam.targets.AlquimiaAgentTarget), and writes the FailureReport / RoastDataset
    via FileFindingsSink. `braintools ingest-findings` then puts it back in the brain.
    """
    typer.echo(
        "The `roast` pipeline is designed but not yet implemented. See CLAUDE.md → "
        "'Roadmap — redteam roast'.",
        err=True,
    )
    raise typer.Exit(code=2)


def main() -> None:  # pragma: no cover - console-script shim
    app()


if __name__ == "__main__":  # pragma: no cover
    sys.exit(app())
