"""The runner's command line: `redteam-runner run <run_id> [--dry-run]`.

One subcommand, and the grammar is pinned on purpose: the dispatchers hand the image `["run",
<id>]`, so a change here is a container that starts and dies. Standard library only -- this is a
job's entrypoint, not a tool a person types into.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

NOTHING_TO_RESUME = 2
"""The exit for a launch the API never accepted: an id outside the rule, or no frozen spec. Said
plainly and exited as "nothing to resume" rather than as a failed attempt."""

FAILED = 1
"""Non-zero so the platform's retry policy -- a Job's backoffLimit -- sees a failed execution and
relaunches. The relaunch resumes from the difference; nothing closed is re-executed. Exiting 0 here
would report a failed run as a successful job, and no retry would come."""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="redteam-runner", description="Run one red-teaming run to completion."
    )
    commands = parser.add_subparsers(dest="command", metavar="command", required=True)
    run = commands.add_parser("run", help="execute the run, resuming whatever the store holds")
    run.add_argument("run_id")
    run.add_argument("--dry-run", action="store_true", help="read the spec and do nothing")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    from redteam_contracts.manifest import RunPhase
    from redteam_contracts.run_id import check
    from redteam_runner.pipeline import execute
    from redteam_settings.config import load
    from redteam_store import layout
    from redteam_store.interface import ObjectNotFound

    try:
        args = build_parser().parse_args(argv)
    except SystemExit as parsed:
        return int(parsed.code or 0)

    try:
        check(args.run_id)
    except ValueError as refused:
        print(refused)
        return NOTHING_TO_RESUME

    settings = load()
    print(
        f"run {args.run_id}: store={settings.store_backend.value} "
        f"secrets={settings.secrets_backend.value}"
    )
    try:
        outcome = execute(args.run_id, settings=settings, dry_run=args.dry_run)
    except ObjectNotFound:
        print(f"no frozen spec at {layout.spec(args.run_id)}; the API has not accepted this run")
        return NOTHING_TO_RESUME

    print(
        f"run {args.run_id}: {outcome.phase.value}, {outcome.n_traces} traces closed, "
        f"{outcome.resumed} of them before this attempt"
        + (f"; webhook {type(outcome.delivery).__name__}" if outcome.delivery else "")
    )
    return FAILED if outcome.phase is RunPhase.FAILED else 0


def cli() -> None:
    sys.exit(main())


if __name__ == "__main__":
    sys.exit(main())
