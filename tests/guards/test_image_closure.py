"""Guard: what is absent from an image is a design guarantee.

The Dockerfiles copy only each app's dependency closure, so an image's contents fall out of the
graph. This pins the properties that matter there, where a future dependency would otherwise erode
them quietly: the runner serves no HTTP and is the one image where generation meets conduction.
"""

from __future__ import annotations

import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from render_dockerfiles import APPS, DIST_PREFIX, _dist_of, closure  # noqa: E402


def _external(app_dir: str) -> set[str]:
    out: set[str] = set()
    for path in {app_dir, *closure(app_dir)}:
        deps = tomllib.loads((ROOT / path / "pyproject.toml").read_text())["project"].get(
            "dependencies", []
        )
        out.update(d for d in map(_dist_of, deps) if not d.startswith(DIST_PREFIX))
    return out


def test_every_workspace_dependency_of_an_app_resolves_to_a_member() -> None:
    members = {
        tomllib.loads(p.read_text())["project"]["name"]
        for p in ROOT.glob("packages/*/pyproject.toml")
    }
    for app in APPS:
        deps = tomllib.loads((ROOT / "apps" / app / "pyproject.toml").read_text())["project"][
            "dependencies"
        ]
        for dist in map(_dist_of, deps):
            if dist.startswith(DIST_PREFIX):
                assert dist in members, f"apps/{app} depends on {dist!r}, which is not a member"


def test_the_runner_is_where_generation_meets_conduction_and_serves_no_http() -> None:
    paths = set(closure("apps/runner"))
    assert {"packages/probes", "packages/engine", "packages/knowledge", "packages/target"} <= paths
    external = _external("apps/runner")
    assert "fastapi" not in external and "uvicorn" not in external


def test_the_api_reaches_neither_the_assistant_nor_a_model_nor_a_brain() -> None:
    """The gate validates, freezes, launches and reads. What it cannot import it cannot do by
    accident: no target adapter, no knowledge client, no judge, no generation, no engine."""
    paths = set(closure("apps/api"))
    for absent in (
        "packages/target",
        "packages/knowledge",
        "packages/judges",
        "packages/probes",
        "packages/engine",
    ):
        assert absent not in paths, f"the API gained {absent}"
    assert "packages/catalogue" in paths, "publishing validates a bundle, which needs the package"
    external = _external("apps/api")
    assert "pyboltzmann" not in external
    assert "fastapi" in external and "uvicorn" in external
