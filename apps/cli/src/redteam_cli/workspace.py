"""The workspace: a `.redteam/` directory beside the operator's work.

What it holds is the operator's, never the platform's: the API to talk to, the credentials the local
stack is brought up with, the bundles they author, and what the API answered about their runs. The
store is the platform's record; this is the operator's notebook.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path

DIRECTORY = ".redteam"
CONFIG = "config.json"
ENV = ".env"
CATALOGUES = "catalogues"
RUNS = "runs"

DEFAULT_API_URL = "http://localhost:8080"
DEFAULT_RECEIVER_URL = "http://localhost:8083"
COMPOSE_PROJECT = "red-teaming"

ENV_TEMPLATE = """\
# Credentials the local stack is brought up with. Read by `redteam local up` and handed to compose;
# never committed. Every value is optional: the mock target checks nothing, and a run naming a
# hosted model is refused at the gate until its key is here.
#
# The key the target's connector names. Any value satisfies the mock target.
TARGET_KEY=mock-target-checks-nothing
# A hosted router's key, for a judge, generator, embedder or attacker with `provider: openrouter`.
OPENROUTER_API_KEY=
# The Alquimia runtime's token, for a run against a real assistant.
ALQUIMIA_API_TOKEN=
# `user:token` for a private brain registry, when a run declares a knowledge base.
BRAIN_REGISTRY_CREDENTIALS=
"""

GITIGNORE = """\
# The operator's credentials and what the API answered about their runs stay on this machine.
.env
runs/
"""


class NoWorkspace(FileNotFoundError):
    def __init__(self, start: Path) -> None:
        super().__init__(
            f"no {DIRECTORY}/{CONFIG} in {start} or any directory above it; run `redteam init` "
            f"where you want the workspace"
        )


@dataclass(frozen=True)
class Config:
    api_url: str = DEFAULT_API_URL
    receiver_url: str = DEFAULT_RECEIVER_URL
    compose_project: str = COMPOSE_PROJECT


@dataclass(frozen=True)
class Workspace:
    root: Path
    """The `.redteam/` directory itself."""

    config: Config

    @property
    def env_file(self) -> Path:
        return self.root / ENV

    @property
    def catalogues(self) -> Path:
        return self.root / CATALOGUES

    def run_dir(self, run_id: str) -> Path:
        path = self.root / RUNS / run_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    def keep(self, run_id: str, name: str, payload: object) -> Path:
        """Write what the API answered about a run beside the operator's other notes on it."""
        path = self.run_dir(run_id) / name
        path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
        return path


def init(
    where: Path,
    *,
    api_url: str = DEFAULT_API_URL,
    receiver_url: str = DEFAULT_RECEIVER_URL,
) -> Workspace:
    """Create the workspace under `where`, or update its configuration if it exists.

    The credentials file is created empty-by-template with owner-only permissions and never
    overwritten: an `init` run again must not wipe keys somebody typed in.
    """
    root = where / DIRECTORY
    root.mkdir(parents=True, exist_ok=True)
    (root / CATALOGUES).mkdir(exist_ok=True)
    (root / RUNS).mkdir(exist_ok=True)
    config = Config(api_url=api_url.rstrip("/"), receiver_url=receiver_url.rstrip("/"))
    (root / CONFIG).write_text(json.dumps(asdict(config), indent=2) + "\n")
    (root / ".gitignore").write_text(GITIGNORE)
    env = root / ENV
    if not env.exists():
        env.write_text(ENV_TEMPLATE)
    os.chmod(env, 0o600)
    return Workspace(root=root, config=config)


def load(start: Path | None = None) -> Workspace:
    """The workspace that governs `start`: the nearest `.redteam/` at or above it."""
    here = (start or Path.cwd()).resolve()
    for candidate in (here, *here.parents):
        config_path = candidate / DIRECTORY / CONFIG
        if config_path.is_file():
            raw = json.loads(config_path.read_text())
            return Workspace(
                root=candidate / DIRECTORY,
                config=Config(**{k: v for k, v in raw.items() if k in Config.__annotations__}),
            )
    raise NoWorkspace(here)


def environment(workspace: Workspace) -> dict[str, str]:
    """The credentials file as a mapping, for compose. Lines are `KEY=value`; blanks and comments
    are skipped; a value the shell would quote is taken verbatim, quotes included."""
    values: dict[str, str] = {}
    if not workspace.env_file.is_file():
        return values
    for line in workspace.env_file.read_text().splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        values[key.strip()] = value.strip()
    return values
