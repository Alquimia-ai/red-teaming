"""The command line: one subcommand, and exit codes the platform's retry policy can read."""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from redteam_runner.main import cli_app


def test_an_id_outside_the_rule_exits_as_nothing_to_resume() -> None:
    result = CliRunner().invoke(cli_app, ["run", "Run_1"])
    assert result.exit_code == 2
    assert "does not follow the rule" in result.output


def test_a_run_the_api_never_accepted_exits_as_nothing_to_resume(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("REDTEAM_STORE_BACKEND", "memory")
    result = CliRunner().invoke(cli_app, ["run", "run-nobody-accepted"])
    assert result.exit_code == 2
    assert "no frozen spec" in result.output


def test_run_is_an_explicit_subcommand() -> None:
    """The dispatchers hand the image `["run", <id>]`; a lone command would read "run" as the
    id."""
    result = CliRunner().invoke(cli_app, ["run-1"])
    assert result.exit_code != 0
