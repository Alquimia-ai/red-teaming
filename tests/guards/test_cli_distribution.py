"""Guard: the command line is installed, updated and released by one set of names.

Three pieces have to agree about the same thing or a person ends up with a command line that
installs from one place and updates from another: `install.sh`, which is curled and run by `sh`;
`redteam_cli.release`, which is what `redteam update` uses; and the release workflow, which decides
which files a `cli-v*` release carries. The agreement is not expressible in one language -- one is
shell, one is Python, one is YAML -- so it is asserted here, by running the installer and reading
the workflows.

What is checked: that a platform resolves to the same asset in the shell and in Python, that both
name the same repository and the same tag prefix, that the matrix builds exactly the assets the
command line knows how to ask for, and that nothing builds a zipapp except the one reusable
workflow -- publishing only when it is handed a release tag.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "apps" / "cli" / "src"))

from redteam_cli import release  # noqa: E402

INSTALLER = ROOT / "install.sh"
WORKFLOWS = ROOT / ".github" / "workflows"
BUILD = WORKFLOWS / "build-cli.yml"

needs_sh = pytest.mark.skipif(sys.platform.startswith("win"), reason="the installer is POSIX sh")

SPELLINGS = [
    # Every way a machine in the matrix, or a machine somebody runs the installer on, names itself.
    ("Linux", "x86_64"),
    ("Linux", "amd64"),
    ("Linux", "aarch64"),
    ("Linux", "arm64"),
    ("linux", "X86_64"),
    ("Darwin", "arm64"),
    ("Darwin", "aarch64"),
    ("Darwin", "x86_64"),
    ("darwin", "ARM64"),
]

UNSUPPORTED = [("Windows", "x86_64"), ("Linux", "riscv64"), ("SunOS", "sparc")]


def _workflow(name: str) -> dict[Any, Any]:
    """A workflow as YAML reads it: `on:` is a YAML 1.1 boolean, so the keys are not all strings."""
    loaded: dict[Any, Any] = yaml.safe_load((WORKFLOWS / name).read_text())
    return loaded


def _triggers(workflow: dict[Any, Any]) -> dict[str, Any]:
    """A workflow's triggers, whichever of the two keys they arrived under."""
    triggers: Any = workflow["on"] if "on" in workflow else workflow[True]
    return dict(triggers or {})


def _installer(*args: str, system: str | None = None, machine: str | None = None) -> str:
    environment = {"PATH": "/usr/bin:/bin:/usr/sbin:/sbin", "HOME": "/tmp"}
    if system is not None:
        environment["REDTEAM_OS"] = system
    if machine is not None:
        environment["REDTEAM_ARCH"] = machine
    done = subprocess.run(
        ["sh", str(INSTALLER), *args],
        capture_output=True,
        text=True,
        cwd=ROOT,
        env=environment,
        check=False,
    )
    return done.stdout.strip() if done.returncode == 0 else ""


def _callers() -> dict[str, dict[str, Any]]:
    """Every job in every workflow that calls the reusable command-line build."""
    called = "./.github/workflows/build-cli.yml"
    jobs: dict[str, dict[str, Any]] = {}
    for path in WORKFLOWS.glob("*.yml"):
        workflow = yaml.safe_load(path.read_text())
        for name, job in (workflow.get("jobs") or {}).items():
            if job.get("uses") == called:
                jobs[f"{path.name}:{name}"] = job
    return jobs


# ---- the installer and the command line resolve the same file -----------------------------------


@needs_sh
@pytest.mark.parametrize(("system", "machine"), SPELLINGS)
def test_the_installer_downloads_what_update_would_download(system: str, machine: str) -> None:
    asset = release.asset_name(system, machine)
    assert asset in release.ASSETS
    assert _installer("--print-asset", system=system, machine=machine) == asset, (
        f"{system}/{machine}: install.sh and redteam_cli.release disagree about which asset this "
        f"platform gets; the first install and every update after it would be different files"
    )


@needs_sh
@pytest.mark.parametrize(("system", "machine"), UNSUPPORTED)
def test_neither_invents_an_asset_for_a_platform_no_release_carries(
    system: str, machine: str
) -> None:
    assert _installer("--print-asset", system=system, machine=machine) == ""
    with pytest.raises(release.Unsupported):
        release.asset_name(system, machine)


RELEASE_JSON = """{
  "tag_name": "cli-v9.9.9",
  "assets": [
    {
      "url": "https://api.github.com/repos/o/r/releases/assets/111",
      "id": 111,
      "name": "redteam-linux-aarch64.pyz",
      "label": null,
      "uploader": {"login": "somebody", "id": 1},
      "browser_download_url": "https://github.com/o/r/releases/download/cli-v9.9.9/x.pyz"
    },
    {
      "url": "https://api.github.com/repos/o/r/releases/assets/222",
      "id": 222,
      "name": "redteam-linux-x86_64.pyz",
      "label": null,
      "uploader": {"login": "somebody", "id": 1},
      "browser_download_url": "https://github.com/o/r/releases/download/cli-v9.9.9/y.pyz"
    }
  ]
}"""
"""A release as the API returns it: the asset's own URL, its name, and a nested object between
them. Written pretty, which is how GitHub answers curl."""


def _shell_function(name: str) -> str:
    """One function, as install.sh defines it, so a test runs the installer's real code."""
    lines = INSTALLER.read_text().splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith(f"{name}() {{"))
    end = next(i for i in range(start + 1, len(lines)) if lines[i] == "}")
    return "\n".join(lines[start : end + 1])


@needs_sh
@pytest.mark.parametrize("shape", ["pretty", "compact"])
def test_the_installer_finds_an_asset_url_in_either_json_shape(tmp_path: Path, shape: str) -> None:
    """A private repository is installed from the asset's API URL, which has to be read out of the
    release JSON. GitHub serves that JSON pretty-printed to curl and compact to other clients; a
    parser that only understood one of them resolved nothing and the install said the release
    carried no asset for this platform.
    """
    payload = RELEASE_JSON if shape == "pretty" else json.dumps(json.loads(RELEASE_JSON))
    fixture = tmp_path / "release.json"
    fixture.write_text(payload)
    script = "\n".join(
        (
            f'api() {{ cat "{fixture}"; }}',
            "GITHUB_API=x; OWNER=o; REPOSITORY=r",
            _shell_function("asset_api_url"),
            "asset_api_url cli-v9.9.9 redteam-linux-aarch64.pyz",
        )
    )
    done = subprocess.run(["sh", "-c", script], capture_output=True, text=True, check=False)
    assert done.stdout.strip() == "https://api.github.com/repos/o/r/releases/assets/111", (
        f"{shape} JSON: the installer resolved {done.stdout.strip()!r}"
    )


def test_the_installer_and_the_command_line_name_the_same_releases() -> None:
    script = INSTALLER.read_text()
    for name, value in (
        ("OWNER", release.OWNER),
        ("REPOSITORY", release.REPOSITORY),
        ("TAG_PREFIX", release.TAG_PREFIX),
    ):
        assert f'{name}="{value}"' in script, (
            f"install.sh does not carry {name}={value!r}; it would install from a different "
            f"repository, or from another component's tags, than `redteam update` reads"
        )


# ---- the matrix builds exactly what can be asked for ---------------------------------------------


def _platform_of(runner: str) -> tuple[str, str]:
    """What a GitHub runner label says it is: its operating system and its architecture."""
    system = {"ubuntu": "linux", "macos": "darwin"}[runner.split("-", 1)[0]]
    if runner.endswith("-arm"):
        return system, "aarch64"
    if runner.endswith("-intel"):
        return system, "x86_64"
    return system, "arm64" if system == "darwin" else "x86_64"


def test_the_release_matrix_builds_every_asset_and_no_other() -> None:
    runners = yaml.safe_load(
        _triggers(_workflow("build-cli.yml"))["workflow_call"]["inputs"]["runners"]["default"]
    )
    built = {release.asset_name(*_platform_of(runner)) for runner in runners}
    assert built == set(release.ASSETS), (
        f"the matrix builds {sorted(built)}, the command line asks for {sorted(release.ASSETS)}; "
        f"a platform in one and not the other is an install that 404s or an asset nobody downloads"
    )
    assert len(runners) == len(built), "two runners build the same asset"


def test_the_zipapp_is_built_in_one_place_and_every_workflow_goes_through_it() -> None:
    build = BUILD.read_text()
    assert "scripts/build_pyz.sh" in build
    for path in WORKFLOWS.glob("*.yml"):
        if path == BUILD:
            continue
        runs = [
            line
            for line in path.read_text().splitlines()
            if "build_pyz.sh" in line and "shellcheck" not in line
        ]
        assert not runs, (
            f"{path.name} builds the command line itself ({runs}); it must call build-cli.yml, or "
            f"what a release publishes and what develop verified are built by two recipes"
        )
    callers = _callers()
    assert {name.split(":")[0] for name in callers} == {
        "ci.yml",
        "cli-develop.yml",
        "release-please.yml",
    }


def test_only_a_release_publishes_the_command_line() -> None:
    """develop builds and verifies; the tag is what publishes. The same rule the images follow."""
    for name, job in _callers().items():
        tag = (job.get("with") or {}).get("release-tag")
        publishes = bool(tag)
        assert publishes == name.startswith("release-please.yml"), (
            f"{name}: only the release workflow may hand build-cli.yml a release tag; a build on "
            f"develop that attached assets would publish an unreleased command line"
        )
        if publishes:
            assert "cli--tag_name" in str(tag), f"{name} publishes to {tag}, not the cli's own tag"


def test_the_right_to_publish_comes_from_the_caller() -> None:
    """A called workflow cannot ask for more than its caller holds, so the build asks for nothing:
    the callers that only verify grant read, and the release grants the write it needs."""
    assert "permissions:" not in BUILD.read_text(), (
        "build-cli.yml declares permissions; a caller that grants less refuses to start the run"
    )
    for name, job in _callers().items():
        granted = (job.get("permissions") or {}).get("contents")
        wanted = "write" if name.startswith("release-please.yml") else "read"
        assert granted == wanted, f"{name} grants contents: {granted}, it needs {wanted}"


def test_develop_builds_the_whole_matrix_and_a_pull_request_one_platform() -> None:
    develop = _workflow("cli-develop.yml")
    assert _triggers(develop)["push"]["branches"] == ["develop"]
    assert "runners" not in (develop["jobs"]["build"].get("with") or {}), (
        "cli-develop.yml must build the default matrix: develop is where every platform a release "
        "publishes is proved"
    )
    on_a_pull_request = yaml.safe_load(_workflow("ci.yml")["jobs"]["cli"]["with"]["runners"])
    assert len(on_a_pull_request) == 1
