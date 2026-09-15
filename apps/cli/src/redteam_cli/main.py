"""`redteam`: the command line.

    redteam init [--api-url] [--receiver-url]      the workspace: .redteam/
    redteam local up [--build] | down | status | logs [service] [-f]
    redteam catalogue validate <file> | publish <file> | list
    redteam prior publish <name> <file>
    redteam run validate <spec> | start <spec> [--follow] [--deadline] | status <id> |
                result <id> | list | resume <id>
    redteam receiver export <run_id>               what the local receiver was delivered
    redteam update [--check] [--tag cli-v0.2.0]    replace this command line with the newest release
    redteam --version                              the version this file was built from

Parsed with the standard library and rendered with rich: tables and panels for a person, `--json`
wherever the API's answer is worth piping. Exit codes are the outcome -- 0 done, 1 the API refused
or the run failed, 2 no workspace, 3 nothing answered, 4 the run is stalled, 5 the deadline passed.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from redteam_cli import api as api_module
from redteam_cli import bundle, local, release, workspace

OK, REFUSED, NO_WORKSPACE, UNREACHABLE, STALLED, DEADLINE = 0, 1, 2, 3, 4, 5
TERMINAL = frozenset({"complete", "failed"})
POLL_SECONDS = 5.0


class Exit(Exception):
    """A command is over, with a code and a message for the person."""

    def __init__(self, code: int, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass
class Context:
    out: Console
    err: Console
    as_json: bool = False

    def show(self, payload: Any) -> None:
        self.out.print_json(data=payload)

    def ws(self) -> workspace.Workspace:
        try:
            return workspace.load()
        except workspace.NoWorkspace as missing:
            raise Exit(NO_WORKSPACE, str(missing)) from missing

    def api(self) -> api_module.Api:
        return api_module.Api(self.ws().config.api_url)

    def asking(self, action: Callable[[], Any]) -> Any:
        """One request, with the API's refusal as the exit and its own words as the message."""
        try:
            return action()
        except api_module.ApiError as refused:
            raise Exit(
                REFUSED, f"the API refused ({refused.status}): {refused.detail}"
            ) from refused
        except api_module.Unreachable as down:
            raise Exit(UNREACHABLE, str(down)) from down


# ---- init and local -----------------------------------------------------------------------------


def cmd_init(args: argparse.Namespace, ctx: Context) -> int:
    created = workspace.init(Path.cwd(), api_url=args.api_url, receiver_url=args.receiver_url)
    ctx.out.print(
        Panel.fit(
            f"[bold]{created.root}[/bold]\n"
            f"api: {created.config.api_url}\n"
            f"receiver: {created.config.receiver_url}\n"
            f"credentials: {created.env_file}  [dim](edit before `redteam local up`)[/dim]",
            title="workspace",
        )
    )
    return OK


def _local(action: Callable[[], None]) -> int:
    try:
        action()
    except (local.NoDocker, local.ComposeFailed, FileNotFoundError) as refused:
        raise Exit(UNREACHABLE, str(refused)) from refused
    return OK


def cmd_local_up(args: argparse.Namespace, ctx: Context) -> int:
    ws = ctx.ws()
    code = _local(lambda: local.up(ws, build=args.build))
    ctx.out.print(f"[green]stack up[/green]; api at {ws.config.api_url}")
    return code


def cmd_local_down(args: argparse.Namespace, ctx: Context) -> int:
    ws = ctx.ws()
    code = _local(lambda: local.down(ws))
    ctx.out.print("[green]stack down[/green]; the volumes stay, and with them every run")
    return code


def cmd_local_status(args: argparse.Namespace, ctx: Context) -> int:
    ws = ctx.ws()
    return _local(lambda: local.status(ws))


def cmd_local_logs(args: argparse.Namespace, ctx: Context) -> int:
    ws = ctx.ws()
    return _local(lambda: local.logs(ws, args.service, follow=args.follow))


# ---- catalogues and priors ----------------------------------------------------------------------


def _bundle_body(path: Path) -> dict[str, Any]:
    try:
        return bundle.read_bundle(path)
    except (bundle.BundleIncomplete, ValueError) as malformed:
        raise Exit(REFUSED, str(malformed)) from malformed


def cmd_catalogue_validate(args: argparse.Namespace, ctx: Context) -> int:
    body = _bundle_body(args.file)
    checked = ctx.asking(lambda: ctx.api().validate_bundle(body))
    if ctx.as_json:
        ctx.show(checked)
        return OK
    table = Table(title=f"{body['name']}: every check passed", show_header=False)
    table.add_row("principles", str(checked.get("principles")))
    table.add_row("strategies", str(checked.get("strategies")))
    table.add_row("requires brain", ", ".join(checked.get("requires_brain") or ()) or "-")
    ctx.out.print(table)
    return OK


def cmd_catalogue_publish(args: argparse.Namespace, ctx: Context) -> int:
    ws = ctx.ws()
    body = _bundle_body(args.file)
    published = ctx.asking(lambda: ctx.api().publish_bundle(body))
    kept = ws.catalogues / str(body["name"])
    kept.mkdir(parents=True, exist_ok=True)
    (kept / "published.json").write_text(json.dumps(published, indent=2, sort_keys=True) + "\n")
    if ctx.as_json:
        ctx.show(published)
        return OK
    verb = "published" if published.get("created") else "already published"
    ctx.out.print(
        f"[bold]{body['name']}[/bold]: {verb} as version [bold]{published['version']}[/bold] "
        f"[dim]({kept / 'published.json'})[/dim]"
    )
    return OK


def cmd_catalogue_list(args: argparse.Namespace, ctx: Context) -> int:
    catalogues = ctx.asking(lambda: ctx.api().catalogues())
    if ctx.as_json:
        ctx.show(catalogues)
        return OK
    table = Table("catalogue", "versions", title="published catalogues")
    for name, versions in sorted(catalogues.items()):
        table.add_row(name, ", ".join(str(v) for v in versions))
    ctx.out.print(table)
    return OK


def cmd_prior_publish(args: argparse.Namespace, ctx: Context) -> int:
    try:
        phrasings = bundle.read_phrasings(args.file)
    except ValueError as malformed:
        raise Exit(REFUSED, str(malformed)) from malformed
    published = ctx.asking(lambda: ctx.api().publish_prior(args.name, phrasings))
    if ctx.as_json:
        ctx.show(published)
        return OK
    verb = "published" if published.get("created") else "already published"
    ctx.out.print(
        f"[bold]{args.name}[/bold]: {verb} as version [bold]{published['version']}[/bold], "
        f"{published.get('size', len(phrasings))} phrasings"
    )
    return OK


# ---- runs ---------------------------------------------------------------------------------------


def _spec(path: Path) -> dict[str, Any]:
    try:
        return bundle.read_spec(path)
    except ValueError as malformed:
        raise Exit(REFUSED, str(malformed)) from malformed


def _status_table(status: dict[str, Any]) -> Table:
    table = Table(title=str(status.get("run_id", "run")), show_header=False)
    phase = str(status["phase"])
    colour = {"complete": "green", "failed": "red"}.get(phase, "yellow")
    table.add_row("phase", f"[{colour}]{phase}[/{colour}]")
    table.add_row("runner", str(status.get("runner")))
    if status.get("stalled"):
        table.add_row("stalled", "[red]yes[/red] -- `redteam run resume` relaunches it")
    table.add_row(
        "planned", str(status.get("planned") if status.get("planned") is not None else "?")
    )
    table.add_row("closed", str(status.get("closed")))
    table.add_row("failed", str(status.get("failed")))
    table.add_row(
        "pending", str(status.get("pending") if status.get("pending") is not None else "?")
    )
    return table


def _manifest_tables(manifest: dict[str, Any]) -> list[Table]:
    summary = Table(title=f"{manifest.get('run_id', 'run')}: manifest", show_header=False)
    summary.add_row("phase", f"[green]{manifest.get('phase')}[/green]")
    summary.add_row("traces", str(manifest.get("n_total_traces")))
    for artifact in ("dataset", "profile", "exploit"):
        summary.add_row(artifact, str(manifest.get(artifact) or "-"))
    coverage = manifest.get("coverage") or {}
    total = coverage.get("total") or {}
    summary.add_row(
        "coverage",
        f"planned {total.get('planned', '?')}, closed {total.get('closed', '?')}, "
        f"failed {total.get('failed', '?')}",
    )
    tables = [summary]
    for slice_name in ("by_plugin", "by_strategy"):
        slices = coverage.get(slice_name) or {}
        if not slices:
            continue
        table = Table(slice_name.removeprefix("by_"), "planned", "closed", "failed")
        for name, counts in sorted(slices.items()):
            table.add_row(
                name,
                str(counts.get("planned")),
                str(counts.get("closed")),
                str(counts.get("failed")),
            )
        tables.append(table)
    components = manifest.get("components") or {}
    if components:
        table = Table("component", "value", title="components")
        for key, value in sorted(components.items()):
            table.add_row(key, str(value))
        tables.append(table)
    return tables


def cmd_run_validate(args: argparse.Namespace, ctx: Context) -> int:
    body = _spec(args.spec)
    validated = ctx.asking(lambda: ctx.api().validate_run(body))
    if ctx.as_json:
        ctx.show(validated)
        return OK
    table = Table(title=f"{validated['run_id']}: the gate passed", show_header=False)
    table.add_row("catalogue versions", json.dumps(validated.get("catalogue_versions")))
    table.add_row("contract", str(validated.get("contract_digest")))
    table.add_row("secret refs", ", ".join(validated.get("secret_refs") or ()) or "-")
    ctx.out.print(table)
    return OK


def cmd_run_start(args: argparse.Namespace, ctx: Context) -> int:
    ws = ctx.ws()
    body = _spec(args.spec)
    accepted = ctx.asking(lambda: ctx.api().start_run(body))
    run_id = str(accepted["run_id"])
    ws.keep(run_id, "accepted.json", accepted)
    launched = (
        "runner launched" if accepted.get("launched", True) else "a runner was already running"
    )
    ctx.out.print(
        f"[bold]{run_id}[/bold]: accepted; {launched}; manifest will appear at "
        f"{accepted['result_location']}"
    )
    if args.follow:
        return _follow(ctx, ws, run_id, args.deadline)
    return OK


def _follow(ctx: Context, ws: workspace.Workspace, run_id: str, deadline: float) -> int:
    api = ctx.api()
    expires = time.monotonic() + deadline
    last = ""
    while True:
        status = ctx.asking(lambda: api.status(run_id))
        line = (
            f"{status['phase']} runner={status['runner']} closed={status['closed']} "
            f"failed={status['failed']} pending={status['pending']}"
        )
        if line != last:
            ctx.out.print(f"[dim]{run_id}[/dim]: {line}")
            last = line
        if status["phase"] in TERMINAL:
            ws.keep(run_id, "status.json", status)
            if status["phase"] != "complete":
                raise Exit(
                    REFUSED,
                    f"{run_id}: the attempt failed; the record is at "
                    f"{ws.run_dir(run_id) / 'status.json'}",
                )
            manifest = ctx.asking(lambda: api.result(run_id))
            ws.keep(run_id, "manifest.json", manifest)
            for table in _manifest_tables(manifest):
                ctx.out.print(table)
            return OK
        if status.get("stalled"):
            raise Exit(
                STALLED,
                f"{run_id} is stalled: the store says {status['phase']} and the platform says the "
                f"runner is {status['runner']}. `redteam run resume {run_id}` relaunches it.",
            )
        if time.monotonic() >= expires:
            raise Exit(
                DEADLINE, f"{run_id} is still {status['phase']} after {deadline:g}s; giving up"
            )
        time.sleep(POLL_SECONDS)


def cmd_run_status(args: argparse.Namespace, ctx: Context) -> int:
    ws = ctx.ws()
    status = ctx.asking(lambda: ctx.api().status(args.run_id))
    ws.keep(args.run_id, "status.json", status)
    if ctx.as_json:
        ctx.show(status)
    else:
        ctx.out.print(_status_table({"run_id": args.run_id, **status}))
    return OK


def cmd_run_result(args: argparse.Namespace, ctx: Context) -> int:
    ws = ctx.ws()
    manifest = ctx.asking(lambda: ctx.api().result(args.run_id))
    kept = ws.keep(args.run_id, "manifest.json", manifest)
    if ctx.as_json:
        ctx.show(manifest)
    else:
        for table in _manifest_tables(manifest):
            ctx.out.print(table)
    ctx.err.print(f"[dim]kept at {kept}[/dim]")
    return OK


def cmd_run_list(args: argparse.Namespace, ctx: Context) -> int:
    runs = ctx.asking(lambda: ctx.api().runs())
    if ctx.as_json:
        ctx.show(runs)
        return OK
    for run_id in runs:
        ctx.out.print(run_id, highlight=False)
    return OK


def cmd_run_resume(args: argparse.Namespace, ctx: Context) -> int:
    relaunched = ctx.asking(lambda: ctx.api().resume(args.run_id))
    if ctx.as_json:
        ctx.show(relaunched)
        return OK
    verb = "runner launched" if relaunched.get("launched") else "a runner was already running"
    ctx.out.print(f"[bold]{args.run_id}[/bold]: {verb}; runner={relaunched.get('runner')}")
    return OK


# ---- receiver -----------------------------------------------------------------------------------


def cmd_receiver_export(args: argparse.Namespace, ctx: Context) -> int:
    ws = ctx.ws()
    receiver = api_module.Receiver(ws.config.receiver_url)
    deliveries = ctx.asking(lambda: receiver.received(args.run_id))
    if not deliveries:
        raise Exit(REFUSED, f"the receiver holds no delivery for {args.run_id}")
    kept = ws.keep(args.run_id, "delivery.json", deliveries)
    ctx.show(deliveries)
    ctx.err.print(f"[dim]kept at {kept}[/dim]")
    return OK


# ---- the command line itself --------------------------------------------------------------------


def _wanted(args: argparse.Namespace, auth: str | None) -> release.Release:
    try:
        return release.at(args.tag, auth=auth) if args.tag else release.latest(auth=auth)
    except release.Unavailable as down:
        raise Exit(UNREACHABLE, str(down)) from down


def cmd_update(args: argparse.Namespace, ctx: Context) -> int:
    """What this command line is, what the newest release is, and -- unless asked only to look --
    the second in place of the first."""
    installed = release.version()
    auth = release.token()
    try:
        asset = release.asset_name()
    except release.Unsupported as unsupported:
        raise Exit(REFUSED, str(unsupported)) from unsupported
    newest = _wanted(args, auth)
    running = release.zipapp()
    available = release.is_newer(newest.version, installed)
    report = {
        "installed": installed,
        "available": newest.version,
        "tag": newest.tag,
        "asset": asset,
        "update_available": available,
        "path": str(running) if running else None,
    }

    if args.check or not (available or args.force):
        if ctx.as_json:
            ctx.show(report)
            return OK
        if available:
            ctx.out.print(
                f"redteam [bold]{installed}[/bold] -> [bold green]{newest.version}[/bold green] "
                f"({newest.tag}); `redteam update` replaces it"
            )
        else:
            ctx.out.print(f"redteam [bold]{installed}[/bold] is the newest release ({newest.tag})")
        return OK

    if running is None:
        raise Exit(
            REFUSED,
            "this command line is not a single file it can replace: it runs from a checkout or an "
            f"environment. Update it the way it was installed (`uv sync --all-packages` in a "
            f"checkout), or install the released one with `curl -fsSL {release.INSTALLER} | sh`",
        )

    ctx.err.print(f"[dim]{newest.tag}: downloading {asset}[/dim]")
    try:
        payload = release.fetch(newest.url(asset), auth=auth)
        published = newest.assets.get(asset + release.CHECKSUM_SUFFIX)
        release.verify(
            payload,
            release.fetch(published, auth=auth).decode() if published else "",
            name=asset,
        )
    except release.Unavailable as down:
        raise Exit(UNREACHABLE, str(down)) from down
    except release.Corrupt as wrong:
        raise Exit(REFUSED, str(wrong)) from wrong
    if published is None:
        ctx.err.print(f"[yellow]{newest.tag} publishes no checksum for {asset}[/yellow]")

    try:
        release.replace(running, payload)
    except OSError as refused:
        raise Exit(
            REFUSED,
            f"{running} could not be replaced ({refused.strerror or refused}); the file belongs to "
            f"another user, or its directory is not writable -- re-run with the rights to write it",
        ) from refused

    if ctx.as_json:
        ctx.show({**report, "updated": True, "installed": newest.version})
        return OK
    ctx.out.print(
        f"[green]redteam {installed} -> {newest.version}[/green] "
        f"[dim]({newest.tag}, {running})[/dim]"
    )
    return OK


class _Version(argparse.Action):
    """`--version` answers before argparse asks for a command, and prints one plain line: the
    version is read by people and by scripts, and rich would wrap it for neither."""

    def __init__(self, option_strings: Sequence[str], dest: str, **kwargs: Any) -> None:
        super().__init__(list(option_strings), dest, nargs=0, **kwargs)

    def __call__(
        self,
        parser: argparse.ArgumentParser,
        namespace: argparse.Namespace,
        values: Any,
        option_string: str | None = None,
    ) -> None:
        print(f"redteam {release.version()}")
        parser.exit(OK)


# ---- the parser ---------------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="redteam", description="Govern red-teaming runs.")
    parser.add_argument(
        "--json", action="store_true", help="print the API's answer as JSON instead of a table"
    )
    parser.add_argument(
        "-V", "--version", action=_Version, help="the version this command line was built from"
    )
    commands = parser.add_subparsers(dest="command", metavar="command", required=True)

    init = commands.add_parser("init", help="create the workspace here: .redteam/")
    init.add_argument("--api-url", default=workspace.DEFAULT_API_URL, help="where the API answers")
    init.add_argument(
        "--receiver-url",
        default=workspace.DEFAULT_RECEIVER_URL,
        help="where the local webhook receiver answers",
    )
    init.set_defaults(handler=cmd_init)

    local_parser = commands.add_parser("local", help="the local stack, through docker compose")
    local_commands = local_parser.add_subparsers(
        dest="local_command", metavar="action", required=True
    )
    up = local_commands.add_parser("up", help="bring the stack up")
    up.add_argument(
        "--build",
        action="store_true",
        help="build the images from this checkout instead of pulling",
    )
    up.set_defaults(handler=cmd_local_up)
    local_commands.add_parser("down", help="stop the stack; volumes stay").set_defaults(
        handler=cmd_local_down
    )
    local_commands.add_parser("status", help="what is running").set_defaults(
        handler=cmd_local_status
    )
    logs = local_commands.add_parser("logs", help="a service's logs")
    logs.add_argument("service", nargs="?", default=None)
    logs.add_argument("-f", "--follow", action="store_true")
    logs.set_defaults(handler=cmd_local_logs)

    catalogue = commands.add_parser("catalogue", help="catalogue bundles")
    catalogue_commands = catalogue.add_subparsers(
        dest="catalogue_command", metavar="action", required=True
    )
    validate = catalogue_commands.add_parser("validate", help="every check publishing runs")
    validate.add_argument("file", type=Path)
    validate.set_defaults(handler=cmd_catalogue_validate)
    publish = catalogue_commands.add_parser("publish", help="the next version of a bundle")
    publish.add_argument("file", type=Path)
    publish.set_defaults(handler=cmd_catalogue_publish)
    catalogue_commands.add_parser("list", help="every published bundle").set_defaults(
        handler=cmd_catalogue_list
    )

    prior = commands.add_parser("prior", help="natural-query priors")
    prior_commands = prior.add_subparsers(dest="prior_command", metavar="action", required=True)
    prior_publish = prior_commands.add_parser(
        "publish", help="a JSON list or one phrasing per line"
    )
    prior_publish.add_argument("name")
    prior_publish.add_argument("file", type=Path)
    prior_publish.set_defaults(handler=cmd_prior_publish)

    run = commands.add_parser("run", help="runs")
    run_commands = run.add_subparsers(dest="run_command", metavar="action", required=True)
    run_validate = run_commands.add_parser("validate", help="the gate alone; nothing written")
    run_validate.add_argument("spec", type=Path)
    run_validate.set_defaults(handler=cmd_run_validate)
    start = run_commands.add_parser("start", help="accept, freeze and launch")
    start.add_argument("spec", type=Path)
    start.add_argument("--follow", action="store_true", help="poll until the run closes or fails")
    start.add_argument(
        "--deadline", type=float, default=1800.0, help="how long --follow waits, in seconds"
    )
    start.set_defaults(handler=cmd_run_start)
    for name, handler, help_text in (
        ("status", cmd_run_status, "phase from the store, liveness from the platform"),
        ("result", cmd_run_result, "the manifest"),
        ("resume", cmd_run_resume, "launch a runner again; it resumes from the difference"),
    ):
        sub = run_commands.add_parser(name, help=help_text)
        sub.add_argument("run_id")
        sub.set_defaults(handler=handler)
    run_commands.add_parser("list", help="every run the deployment accepted").set_defaults(
        handler=cmd_run_list
    )

    receiver = commands.add_parser("receiver", help="the local webhook receiver")
    receiver_commands = receiver.add_subparsers(
        dest="receiver_command", metavar="action", required=True
    )
    export = receiver_commands.add_parser("export", help="what the receiver was delivered")
    export.add_argument("run_id")
    export.set_defaults(handler=cmd_receiver_export)

    update = commands.add_parser("update", help="replace this command line with the newest release")
    update.add_argument(
        "--check", action="store_true", help="say what is available and change nothing"
    )
    update.add_argument(
        "--tag", default=None, help="a release to install instead of the newest, e.g. cli-v0.1.0"
    )
    update.add_argument(
        "--force", action="store_true", help="install it even when it is not newer than this one"
    )
    update.set_defaults(handler=cmd_update)
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    out: Console | None = None,
    err: Console | None = None,
) -> int:
    """Parse, run, and turn the outcome into an exit code. Never raises for a refusal."""
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as parsed:
        return int(parsed.code or 0)
    ctx = Context(
        out=out or Console(),
        err=err or Console(stderr=True),
        as_json=bool(args.json),
    )
    handler: Callable[[argparse.Namespace, Context], int] = args.handler
    try:
        return handler(args, ctx)
    except Exit as over:
        ctx.err.print(f"[red]{over.message}[/red]", highlight=False)
        return over.code


def cli() -> None:
    sys.exit(main())


if __name__ == "__main__":
    sys.exit(main())
