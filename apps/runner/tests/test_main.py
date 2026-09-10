"""The command line: one subcommand, and exit codes the platform's retry policy can read."""

from __future__ import annotations

import pytest

from redteam_runner.main import main


def test_an_id_outside_the_rule_exits_as_nothing_to_resume(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["run", "Run_1"]) == 2
    assert "does not follow the rule" in capsys.readouterr().out


def test_a_run_the_api_never_accepted_exits_as_nothing_to_resume(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("REDTEAM_STORE_BACKEND", "memory")
    assert main(["run", "run-nobody-accepted"]) == 2
    assert "no frozen spec" in capsys.readouterr().out


def test_run_is_an_explicit_subcommand(capsys: pytest.CaptureFixture[str]) -> None:
    """The dispatchers hand the image `["run", <id>]`; a lone positional would read "run" as the
    id."""
    assert main(["run-1"]) != 0
    assert main([]) != 0
