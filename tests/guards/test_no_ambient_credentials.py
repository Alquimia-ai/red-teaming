"""Guard: nothing on the measurement surface reads a credential off the process environment.

A `secret_ref` is resolved by the deployment's `SecretResolver` and nowhere else. A builder that
read the environment itself measured, under any other backend, with whatever key the process
happened to hold -- a credential the spec never declared -- or failed with a 401 far from its
cause. The judges, the knowledge client, the target adapters and probe generation are the surface
this holds for; the dispatcher inheriting the API's environment for a local subprocess, and the
secrets package's own `env` backend, are different things and are not covered here.

Read off the syntax tree rather than by substring: `from os import environ` is a read the substring
missed, and a docstring that mentions the rule is not a violation of it.
"""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SURFACE = (
    "packages/judges/src",
    "packages/knowledge/src",
    "packages/target/src",
    "packages/probes/src",
)

ENVIRONMENT = frozenset({"environ", "environb", "getenv", "getenvb"})
"""Every name in `os` that answers with the process environment."""


def environment_reads(source: str) -> list[str]:
    """Every way `source` reaches the process environment, as `line: what`.

    Two passes, because a use can sit above the import that makes it one: first every name the
    module binds to `os`, then every attribute of those names that reads the environment, plus
    every `from os import` of one.
    """
    tree = ast.parse(source)
    bound_to_os: set[str] = set()
    hits: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            bound_to_os.update(a.asname or a.name for a in node.names if a.name == "os")
        elif isinstance(node, ast.ImportFrom) and node.module == "os":
            hits.extend(
                f"{node.lineno}: from os import {a.name}"
                for a in node.names
                if a.name in ENVIRONMENT
            )
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id in bound_to_os
            and node.attr in ENVIRONMENT
        ):
            hits.append(f"{node.lineno}: {node.value.id}.{node.attr}")
    return sorted(hits)


def test_the_model_facing_surface_never_reads_the_environment_for_a_credential() -> None:
    offenders = [
        f"{path.relative_to(ROOT)}:{hit}"
        for surface in SURFACE
        if (ROOT / surface).is_dir()
        for path in sorted((ROOT / surface).rglob("*.py"))
        for hit in environment_reads(path.read_text())
    ]
    assert not offenders, (
        f"{offenders} read the process environment; a credential comes from the SecretResolver"
    )


def test_the_guard_sees_every_way_to_the_environment_and_ignores_prose() -> None:
    """A guard has to be checked to fail. Each read here is one a substring check for `os.environ`
    and `getenv(` missed, and the last case is the docstring that tripped it."""
    assert environment_reads("import os\nkey = os.environ.get('K')\n")
    assert environment_reads("import os\nkey = os.getenv('K')\n")
    assert environment_reads("from os import environ\nkey = environ.get('K')\n")
    assert environment_reads("from os import getenv\n")
    assert environment_reads("import os as _os\nkey = _os.environ['K']\n")
    assert environment_reads("def f():\n    return os.environb\nimport os\n")
    assert not environment_reads(
        '"""Never read os.environ or getenv() here."""\nimport os\nsep = os.sep\n'
    )
