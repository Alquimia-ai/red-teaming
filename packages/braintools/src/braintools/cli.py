"""The ``braintools`` command-line entry point.

Curates the Boltzmann brain through vitruvio, and exports/ingests the data artifacts
that cross the boundary to the red-teaming app (knowledge out, findings in). Every data
command emits the ``data`` from vitruvio's JSON envelope — the brain returns evidence,
never prose. Failures and warnings are surfaced on stderr.
"""

from __future__ import annotations

import datetime
import json
import os
import re
import shutil
import subprocess
import tempfile
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
    subject: Annotated[
        str | None, typer.Option(help="Restrict to one subject, e.g. roastme or sparring.")
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
                text, limit=limit, memory_types=memory_type,
                subject=subject, mode=mode, content=content,
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


# -- reproducible seed from source ---------------------------------------------

_MARKDOWN_EXTS = {".md", ".markdown"}
# Names skipped by seed: docs about the convention, not knowledge for the brain.
_SEED_SKIP_NAMES = {"readme.md", "template.md"}


def _subject_for(path: Path, root: Path, default: str) -> str:
    """Subject = the immediate subdirectory under the sources root, else the default."""
    rel = path.relative_to(root)
    return rel.parts[0] if len(rel.parts) > 1 else default


def _slugify(text: str) -> str:
    """A filesystem- and URL-safe slug: lowercase, alphanumerics joined by hyphens."""
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:60] or "untitled"


def _tex_to_markdown(tex: Path, out_dir: Path) -> Path:
    """Convert a LaTeX source to GitHub-flavored Markdown with pandoc."""
    if shutil.which("pandoc") is None:
        typer.echo(
            f"pandoc is required to seed LaTeX sources ({tex.name}) but was not found. "
            "Install it (e.g. `brew install pandoc`) and retry.",
            err=True,
        )
        raise typer.Exit(code=127)
    md = out_dir / (tex.stem + ".md")
    proc = subprocess.run(  # noqa: S603 - args are our own + a user-provided path
        ["pandoc", "-f", "latex", "-t", "gfm", str(tex), "-o", str(md)],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        typer.echo(f"pandoc failed on {tex.name}: {proc.stderr.strip()}", err=True)
        raise typer.Exit(code=1)
    return md


@app.command("seed")
def seed(
    sources: Annotated[
        Path | None,
        typer.Option(help="Sources root. Default: $BRAINTOOLS_SOURCES_DIR."),
    ] = None,
    default_subject: Annotated[
        str, typer.Option("--default-subject", help="Subject for files not in a subdir.")
    ] = "misc",
    actor: Annotated[str | None, typer.Option()] = None,
    actor_kind: Annotated[str | None, typer.Option()] = None,
) -> None:
    """Rebuild the brain deterministically from committed source documents.

    Ingests every file under the sources root (Markdown directly; LaTeX via a pandoc
    conversion, with --origin pointing at the .tex), then builds the indices. Each block
    is tagged with the subject of its subdirectory (docs/sources/sparring/* -> "sparring").
    Idempotent: identical content dedupes to the same content-addressed blocks.
    """
    src = sources or config.sources_dir()
    if not src.is_dir():
        typer.echo(f"sources directory not found: {src}", err=True)
        raise typer.Exit(code=1)

    b = _brain()
    _guard(lambda: b.init(actor=actor, actor_kind=actor_kind))  # opens if it exists

    files = sorted(p for p in src.rglob("*") if p.is_file())
    ingested: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        for f in files:
            ext = f.suffix.lower()
            if f.name.lower() in _SEED_SKIP_NAMES or f.name.startswith("."):
                continue
            subj = _subject_for(f, src, default_subject)
            if ext in _MARKDOWN_EXTS:
                res = _guard(lambda f=f, s=subj: b.ingest(f, subject=s))
            elif ext == ".tex":
                md = _tex_to_markdown(f, tmp)
                res = _guard(
                    lambda md=md, f=f, s=subj: b.ingest(
                        md, media_type="text/markdown", subject=s, origin=str(f)
                    )
                )
            else:
                ingested.append({"file": f.name, "skipped": "unsupported extension"})
                continue
            proposed = (res.data or {}).get("proposed") if isinstance(res.data, dict) else None
            ingested.append({"file": f.name, "subject": subj, "proposed": proposed})

    index_res = _guard(lambda: b.index())
    _emit(Result(data={"sources": str(src), "ingested": ingested, "indexed": True},
                 warnings=index_res.warnings))


# -- sparring capture ----------------------------------------------------------

_SPARRING_TEMPLATE = """\
# {title}

- Date: {date}
- Author: {author}
- Target: {target}
- Context: {context}

## What we tried


## What happened


## Takeaway

"""


@app.command("spar")
def spar(
    title: Annotated[str, typer.Argument(help="Title of the finding/insight.")],
    author: Annotated[str | None, typer.Option(help="Defaults to $USER.")] = None,
    target: Annotated[str, typer.Option(help="Agent/model under test, or N/A.")] = "N/A",
    context: Annotated[str, typer.Option(help="One-line context.")] = "",
) -> None:
    """Scaffold a sparring source document under docs/sources/sparring/.

    Creates a dated, structured Markdown file for `seed` to ingest (subject "sparring").
    Fill it in, commit it, then `braintools seed`. This is how interactive sparring
    becomes reproducible, git-shared knowledge.
    """
    author = author or os.environ.get("USER") or "unknown"
    date = datetime.date.today().isoformat()
    name = f"{date}-{_slugify(author)}-{_slugify(title)}.md"
    spar_dir = config.sources_dir() / "sparring"
    spar_dir.mkdir(parents=True, exist_ok=True)
    path = spar_dir / name
    if path.exists():
        typer.echo(f"already exists: {path}", err=True)
        raise typer.Exit(code=1)
    path.write_text(
        _SPARRING_TEMPLATE.format(
            title=title, date=date, author=author, target=target, context=context
        ),
        encoding="utf-8",
    )
    typer.echo(f"created {path}", err=True)
    typer.echo(str(path))  # stdout: the path, so it is scriptable / openable


# -- distribution (OCI registry) -----------------------------------------------

def _extract_digest(data: Any) -> str | None:
    """Best-effort snapshot digest from a push/pull envelope."""
    if not isinstance(data, dict):
        return None
    for key in ("digest", "snapshot", "pushed", "manifest"):
        val = data.get(key)
        if isinstance(val, str) and val.startswith("sha256:"):
            return val
        if isinstance(val, dict):
            for k in ("digest", "snapshot"):
                if isinstance(val.get(k), str):
                    return val[k]
    return None


@app.command("publish")
def publish(
    tag: Annotated[str, typer.Argument(help="Tag to publish under, e.g. v1.")],
    reference: Annotated[
        str | None, typer.Option(help="host/namespace/repo. Default: configured registry.")
    ] = None,
    local: Annotated[
        str | None,
        typer.Option(help="Publish to a filesystem OCI registry dir (no network/creds)."),
    ] = None,
    anonymous: Annotated[bool, typer.Option("--anonymous")] = False,
) -> None:
    """Publish the brain to the registry and update brain.lock (the committed pin)."""
    ref = reference or config.registry_reference()
    result = _guard(
        lambda: _brain().push(reference=ref, tag=tag, local=local, anonymous=anonymous)
    )
    lock = {"reference": ref, "tag": tag, "digest": _extract_digest(result.data)}
    config.lock_path().write_text(json.dumps(lock, indent=2) + "\n", encoding="utf-8")
    typer.echo(f"wrote {config.LOCK_FILE}: {lock['reference']}:{lock['tag']}", err=True)
    _emit(result)


@app.command("pull")
def pull(
    tag: Annotated[str | None, typer.Option(help="Tag to pull. Default: brain.lock.")] = None,
    reference: Annotated[
        str | None, typer.Option(help="host/namespace/repo. Default: brain.lock or configured.")
    ] = None,
    local: Annotated[
        str | None, typer.Option(help="Pull from a filesystem OCI registry dir.")
    ] = None,
    anonymous: Annotated[bool, typer.Option("--anonymous")] = False,
    verify: Annotated[bool, typer.Option("--verify/--no-verify")] = True,
) -> None:
    """Install the brain from the registry (pinned by brain.lock) and verify it."""
    lock: dict[str, Any] = {}
    if config.lock_path().exists():
        lock = json.loads(config.lock_path().read_text(encoding="utf-8"))
    ref = reference or lock.get("reference") or config.registry_reference()
    tg = tag or lock.get("tag")
    b = _brain()
    _guard(lambda: b.init())  # dist pull installs into an existing brain; create if absent
    result = _guard(
        lambda: b.pull(reference=ref, tag=tg, local=local, anonymous=anonymous)
    )
    if verify:
        v = _guard(lambda: _brain().verify())
        verified = (v.data or {}).get("verified") if isinstance(v.data, dict) else None
        typer.echo(f"brain verify: verified={verified}", err=True)
    _emit(result)
