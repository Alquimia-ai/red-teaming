"""The workspace: the operator's notebook, found from anywhere below it."""

from __future__ import annotations

import json
import stat
from pathlib import Path

import pytest

from redteam_cli import workspace


def test_init_creates_the_directory_the_configuration_and_a_private_credentials_file(
    tmp_path: Path,
) -> None:
    created = workspace.init(tmp_path, api_url="http://api:1/", receiver_url="http://r:2")

    assert created.root == tmp_path / ".redteam"
    assert json.loads((created.root / "config.json").read_text()) == {
        "api_url": "http://api:1",
        "receiver_url": "http://r:2",
        "compose_project": "red-teaming",
    }
    assert (created.root / "catalogues").is_dir() and (created.root / "runs").is_dir()
    assert stat.S_IMODE(created.env_file.stat().st_mode) == 0o600
    assert "TARGET_KEY=" in created.env_file.read_text()
    assert ".env" in (created.root / ".gitignore").read_text()


def test_init_again_keeps_the_credentials_somebody_typed(tmp_path: Path) -> None:
    first = workspace.init(tmp_path)
    first.env_file.write_text("OPENROUTER_API_KEY=sk-real\n")

    again = workspace.init(tmp_path, api_url="http://elsewhere:9")

    assert again.env_file.read_text() == "OPENROUTER_API_KEY=sk-real\n"
    assert again.config.api_url == "http://elsewhere:9"


def test_load_finds_the_workspace_from_a_directory_below_it(tmp_path: Path) -> None:
    workspace.init(tmp_path, api_url="http://api:1")
    below = tmp_path / "engagements" / "acme"
    below.mkdir(parents=True)

    found = workspace.load(below)

    assert found.root == tmp_path / ".redteam"
    assert found.config.api_url == "http://api:1"


def test_no_workspace_says_where_it_looked_and_what_to_run(tmp_path: Path) -> None:
    with pytest.raises(workspace.NoWorkspace, match="redteam init"):
        workspace.load(tmp_path)


def test_the_credentials_file_reads_as_a_mapping_skipping_comments_and_blanks(
    tmp_path: Path,
) -> None:
    created = workspace.init(tmp_path)
    created.env_file.write_text("# a comment\n\nTARGET_KEY=t\nOPENROUTER_API_KEY=\nBAD LINE\n")

    assert workspace.environment(created) == {"TARGET_KEY": "t", "OPENROUTER_API_KEY": ""}


def test_what_the_api_answered_is_kept_under_the_run(tmp_path: Path) -> None:
    created = workspace.init(tmp_path)

    kept = created.keep("run-1", "status.json", {"phase": "complete"})

    assert kept == created.root / "runs" / "run-1" / "status.json"
    assert json.loads(kept.read_text()) == {"phase": "complete"}
