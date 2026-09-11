"""Guard: a component is released when something it ships changed, and only then.

release-please attributes a commit to a component by the paths it touched, so `include-paths` has to
be the component's whole dependency closure -- a fix in the store package is a fix in the API and in
the runner, and a release that did not carry it would ship the bug under a new version. Hand
maintained, the list drifts the same way a Dockerfile's COPY list does; this holds it to the graph.
"""

from __future__ import annotations

import json
import sys
import tomllib
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from render_dockerfiles import closure  # noqa: E402

CONFIG = ROOT / "release-please-config.json"
MANIFEST = ROOT / ".release-please-manifest.json"

SHIPS_TOO: dict[str, set[str]] = {"apps/cli": {"deploy/compose", "deploy/seed"}}
"""Paths a component ships beyond its Python closure: the command line carries the local stack."""

ALWAYS = {"uv.lock"}
"""A dependency bump is a change to every component: the lock is in every closure."""


def _config() -> dict[str, dict[str, Any]]:
    packages: dict[str, dict[str, Any]] = json.loads(CONFIG.read_text())["packages"]
    return packages


def test_every_app_is_a_released_component_and_nothing_else_is() -> None:
    apps = {f"apps/{p.parent.name}" for p in ROOT.glob("apps/*/pyproject.toml")}
    assert set(_config()) == apps


def test_include_paths_are_the_dependency_closure() -> None:
    for app, package in _config().items():
        expected = {app, *closure(app), *SHIPS_TOO.get(app, set()), *ALWAYS}
        declared = set(package["include-paths"])
        assert declared == expected, (
            f"{app}: include-paths {sorted(declared ^ expected)} disagree with the closure; a "
            f"change there would ship under no version, or a version would ship no change"
        )


def test_the_manifest_names_every_component_at_the_version_its_pyproject_carries() -> None:
    manifest: dict[str, str] = json.loads(MANIFEST.read_text())
    assert set(manifest) == set(_config())
    for app, version in manifest.items():
        pyproject = tomllib.loads((ROOT / app / "pyproject.toml").read_text())
        assert pyproject["project"]["version"] == version, (
            f"{app}: pyproject says {pyproject['project']['version']}, the manifest {version}; "
            f"release-please bumps both together"
        )


def test_components_are_tagged_apart_and_bumped_pre_major() -> None:
    config = json.loads(CONFIG.read_text())
    assert config["include-component-in-tag"] is True and config["tag-separator"] == "-"
    assert config["separate-pull-requests"] is True
    assert config["bump-minor-pre-major"] is True
    assert {p["component"] for p in config["packages"].values()} == {"api", "runner", "cli"}
    assert all(p["release-type"] == "python" for p in config["packages"].values())
