"""`redteam --version` and `redteam update`: what the command line says it is, what it reads off
the releases API, and what it does to the file it is running from."""

from __future__ import annotations

import hashlib
import io
import json
import re
import zipfile
from pathlib import Path
from typing import Any

import httpx
import pytest
from rich.console import Console

from redteam_cli import main as main_module
from redteam_cli import release
from redteam_cli.main import OK, REFUSED, UNREACHABLE, main

DOWNLOAD = "https://github.com/Alquimia-ai/red-teaming/releases/download"


def zipapp_bytes(marker: str = "redteam") -> bytes:
    """Something that is a zipapp as far as anything downloading one can tell."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("__main__.py", f"# {marker}\n")
    return buffer.getvalue()


def published(tag: str, *assets: str, draft: bool = False) -> dict[str, Any]:
    return {
        "tag_name": tag,
        "draft": draft,
        "assets": [_asset(tag, name) for name in assets],
    }


def _asset(tag: str, name: str) -> dict[str, str]:
    return {
        "name": name,
        "browser_download_url": f"{DOWNLOAD}/{tag}/{name}",
        "url": f"https://api.github.com/repos/Alquimia-ai/red-teaming/releases/assets/{tag}-{name}",
    }


class _GitHub:
    """The releases API, answering from a table of releases, remembering every request."""

    def __init__(self, *releases: dict[str, Any]) -> None:
        self.releases = list(releases)
        self.files: dict[str, bytes] = {}
        self.requests: list[str] = []

    def publish(self, tag: str, name: str, payload: bytes, *, checksum: bool = True) -> None:
        """Attach a file to a release: the asset as the API lists it, and its bytes."""
        self._attach(tag, name, payload)
        if checksum:
            digest = hashlib.sha256(payload).hexdigest()
            self._attach(tag, f"{name}.sha256", f"{digest}  {name}\n".encode())

    def _attach(self, tag: str, name: str, payload: bytes) -> None:
        release_json = next(item for item in self.releases if item["tag_name"] == tag)
        listed = {asset["name"] for asset in release_json["assets"]}
        if name not in listed:
            release_json["assets"].append(_asset(tag, name))
        self.files[f"{DOWNLOAD}/{tag}/{name}"] = payload

    def __call__(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        self.requests.append(url)
        if url in self.files:
            return httpx.Response(200, content=self.files[url])
        if "/releases/tags/" in url:
            tag = url.rsplit("/", 1)[-1]
            for item in self.releases:
                if item["tag_name"] == tag:
                    return httpx.Response(200, json=item)
            return httpx.Response(404, json={"message": "Not Found"})
        if url.endswith("/releases") or "/releases?" in url:
            page = int(httpx.URL(url).params.get("page", "1"))
            return httpx.Response(200, json=self.releases if page == 1 else [])
        return httpx.Response(404, json={"message": f"no route {url}"})


class _Run:
    """`main` with both consoles captured, so a test reads what a person would."""

    def __init__(self) -> None:
        self.out = io.StringIO()
        self.err = io.StringIO()

    def __call__(self, *args: str) -> int:
        return main(
            list(args),
            out=Console(file=self.out, width=200, force_terminal=False, no_color=True),
            err=Console(file=self.err, width=200, force_terminal=False, no_color=True),
        )

    @property
    def stdout(self) -> str:
        return self.out.getvalue()

    @property
    def stderr(self) -> str:
        return self.err.getvalue()


@pytest.fixture
def run() -> _Run:
    return _Run()


@pytest.fixture
def github(monkeypatch: pytest.MonkeyPatch) -> _GitHub:
    """A repository whose newest release is somebody else's, and whose newest command line is
    `cli-v0.9.0`."""
    answering = _GitHub(
        published("runner-v2.0.0"),
        published("cli-v0.9.0"),
        published("api-v1.4.0"),
        published("cli-v0.8.0"),
    )
    monkeypatch.setattr(release, "transport", lambda: httpx.MockTransport(answering))
    monkeypatch.setattr(release, "version", lambda: "0.8.0")
    monkeypatch.setattr(release, "asset_name", lambda *a, **k: "redteam-linux-x86_64.pyz")
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("REDTEAM_GITHUB_TOKEN", raising=False)
    return answering


@pytest.fixture
def installed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A `redteam` on disk that this process is pretending to be running from."""
    target = tmp_path / "bin" / "redteam"
    target.parent.mkdir()
    target.write_bytes(zipapp_bytes("the old one"))
    target.chmod(0o755)
    monkeypatch.setattr(release, "zipapp", lambda: target)
    return target


# ---- what this build is -------------------------------------------------------------------------


def test_version_prints_one_plain_line_and_stops(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--version"]) == OK
    printed = capsys.readouterr().out.strip()
    assert printed == f"redteam {release.version()}"
    assert printed.count("\n") == 0


def test_a_platform_resolves_to_the_asset_its_release_carries() -> None:
    assert release.asset_name("Linux", "x86_64") == "redteam-linux-x86_64.pyz"
    assert release.asset_name("Linux", "amd64") == "redteam-linux-x86_64.pyz"
    assert release.asset_name("Darwin", "arm64") == "redteam-darwin-arm64.pyz"
    assert set(release.ASSETS) == {
        release.asset_name(system, machine)
        for system, machine in (
            ("Linux", "x86_64"),
            ("Linux", "aarch64"),
            ("Darwin", "arm64"),
            ("Darwin", "x86_64"),
        )
    }
    with pytest.raises(release.Unsupported, match="no release asset"):
        release.asset_name("Windows", "x86_64")


def test_versions_are_ordered_by_their_numbers_not_their_text() -> None:
    assert release.is_newer("0.10.0", "0.9.0")
    assert release.is_newer("1.0.0", "0.99.9")
    assert not release.is_newer("0.8.0", "0.8.0")
    assert release.ordinal("cli-v1.2.3") == release.ordinal("1.2.3") == (1, 2, 3)


# ---- reading the releases API --------------------------------------------------------------------


def test_the_newest_release_is_the_command_lines_own_tag(github: _GitHub) -> None:
    newest = release.latest()
    assert newest.tag == "cli-v0.9.0"
    assert newest.version == "0.9.0"


def test_a_named_release_takes_a_tag_or_a_bare_version(github: _GitHub) -> None:
    assert release.at("cli-v0.8.0").tag == "cli-v0.8.0"
    assert release.at("0.8.0").tag == "cli-v0.8.0"
    with pytest.raises(release.Unavailable, match=re.escape("no release tagged cli-v3.0.0")):
        release.at("3.0.0")


def test_a_repository_with_no_command_line_release_says_so(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        release, "transport", lambda: httpx.MockTransport(_GitHub(published("api-v1.0.0")))
    )
    with pytest.raises(release.Unavailable, match="no cli-v"):
        release.latest()


# ---- checking ------------------------------------------------------------------------------------


def test_check_reports_what_is_available_and_changes_nothing(
    github: _GitHub, installed: Path, run: _Run
) -> None:
    before = installed.read_bytes()
    assert run("--json", "update", "--check") == OK
    report = json.loads(run.stdout)
    assert report == {
        "installed": "0.8.0",
        "available": "0.9.0",
        "tag": "cli-v0.9.0",
        "asset": "redteam-linux-x86_64.pyz",
        "update_available": True,
        "path": str(installed),
    }
    assert installed.read_bytes() == before


def test_the_newest_one_already_installed_is_not_an_error(
    github: _GitHub, installed: Path, run: _Run, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(release, "version", lambda: "0.9.0")
    assert run("update") == OK
    assert "is the newest release" in run.stdout
    assert github.files == {}


def test_an_unreachable_api_is_not_a_failed_update(
    installed: Path, run: _Run, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route to host")

    monkeypatch.setattr(release, "transport", lambda: httpx.MockTransport(refuse))
    assert run("update", "--check") == UNREACHABLE
    assert "did not answer" in run.stderr


# ---- replacing the file --------------------------------------------------------------------------


def test_update_replaces_the_running_file_with_the_release_it_verified(
    github: _GitHub, installed: Path, run: _Run
) -> None:
    payload = zipapp_bytes("the new one")
    github.publish("cli-v0.9.0", "redteam-linux-x86_64.pyz", payload)
    assert run("update") == OK
    assert installed.read_bytes() == payload
    assert installed.stat().st_mode & 0o111, "the replacement is executable"
    assert "0.8.0 -> 0.9.0" in run.stdout
    assert not list(installed.parent.glob(".*incoming*")), "nothing is left behind"


def test_a_download_that_does_not_hash_to_what_the_release_published_is_refused(
    github: _GitHub, installed: Path, run: _Run
) -> None:
    before = installed.read_bytes()
    github.publish("cli-v0.9.0", "redteam-linux-x86_64.pyz", zipapp_bytes("the new one"))
    github.files[f"{DOWNLOAD}/cli-v0.9.0/redteam-linux-x86_64.pyz"] = zipapp_bytes("something else")
    assert run("update") == REFUSED
    assert "publishes" in run.stderr
    assert installed.read_bytes() == before, "the command line is untouched"


def test_a_download_that_is_not_a_zipapp_is_refused(
    github: _GitHub, installed: Path, run: _Run
) -> None:
    before = installed.read_bytes()
    github.publish("cli-v0.9.0", "redteam-linux-x86_64.pyz", b"<html>an error page</html>")
    assert run("update") == REFUSED
    assert "not a zipapp" in run.stderr
    assert installed.read_bytes() == before


def test_a_release_with_no_checksum_is_installed_and_said_so(
    github: _GitHub, installed: Path, run: _Run
) -> None:
    payload = zipapp_bytes("the new one")
    github.publish("cli-v0.9.0", "redteam-linux-x86_64.pyz", payload, checksum=False)
    assert run("update") == OK
    assert "no checksum" in run.stderr
    assert installed.read_bytes() == payload


def test_a_tag_installs_that_release_even_when_it_is_older(
    github: _GitHub, installed: Path, run: _Run
) -> None:
    payload = zipapp_bytes("the older one")
    github.publish("cli-v0.8.0", "redteam-linux-x86_64.pyz", payload)
    assert run("update", "--tag", "cli-v0.8.0", "--force") == OK
    assert installed.read_bytes() == payload


def test_a_command_line_that_is_not_one_file_says_how_it_is_updated(
    github: _GitHub, run: _Run, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(release, "zipapp", lambda: None)
    assert run("update") == REFUSED
    assert "install.sh" in run.stderr
    assert "uv sync" in run.stderr


def test_a_file_that_cannot_be_written_names_the_file(
    github: _GitHub, installed: Path, run: _Run, monkeypatch: pytest.MonkeyPatch
) -> None:
    github.publish("cli-v0.9.0", "redteam-linux-x86_64.pyz", zipapp_bytes("the new one"))

    def refuse(target: Path, payload: bytes) -> None:
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(release, "replace", refuse)
    assert run("update") == REFUSED
    assert str(installed) in run.stderr


def test_a_release_without_this_platforms_asset_is_not_a_silent_success(
    github: _GitHub, installed: Path, run: _Run, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(release, "asset_name", lambda *a, **k: "redteam-darwin-arm64.pyz")
    assert run("update") == UNREACHABLE
    assert "carries no redteam-darwin-arm64.pyz" in run.stderr


def test_the_update_command_is_in_the_help(run: _Run) -> None:
    assert main_module.build_parser().format_help().count("update") >= 1
