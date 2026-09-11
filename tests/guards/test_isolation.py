"""Which package may import which. The architecture's boundaries, checked without building an image.

Generation never reaches the assistant and conduction never reads the knowledge base: that is a
property of the code, so it is enforced on imports rather than trusted to image composition. The
runner is the only place both halves meet; the API carries neither the target nor the knowledge
client nor a model. A package that is not in the table cannot be imported by anyone until somebody
adds it here, deliberately.
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

ALLOWED: dict[str, frozenset[str]] = {
    "redteam_contracts": frozenset(),
    "redteam_settings": frozenset(),
    "redteam_secrets": frozenset(),
    "redteam_delivery": frozenset(),
    "redteam_store": frozenset({"redteam_contracts"}),
    "redteam_dispatch": frozenset({"redteam_contracts", "redteam_settings", "redteam_secrets"}),
    "redteam_knowledge": frozenset({"redteam_contracts"}),
    "redteam_judges": frozenset({"redteam_contracts"}),
    "redteam_target": frozenset({"redteam_contracts"}),
    "redteam_catalogue": frozenset({"redteam_contracts", "redteam_store"}),
    "redteam_probes": frozenset(
        {
            "redteam_contracts",
            "redteam_store",
            "redteam_catalogue",
            "redteam_knowledge",
            "redteam_judges",
        }
    ),
    "redteam_engine": frozenset(
        {
            "redteam_contracts",
            "redteam_store",
            "redteam_catalogue",
            "redteam_target",
            "redteam_judges",
        }
    ),
    "redteam_api": frozenset(
        {
            "redteam_contracts",
            "redteam_settings",
            "redteam_secrets",
            "redteam_store",
            "redteam_dispatch",
            "redteam_catalogue",
        }
    ),
    "redteam_runner": frozenset(
        {
            "redteam_contracts",
            "redteam_settings",
            "redteam_secrets",
            "redteam_store",
            "redteam_delivery",
            "redteam_knowledge",
            "redteam_judges",
            "redteam_target",
            "redteam_catalogue",
            "redteam_probes",
            "redteam_engine",
        }
    ),
    "redteam_cli": frozenset({"redteam_contracts"}),
}

THIRD_PARTY_ONLY_IN: dict[str, str] = {
    "pyboltzmann": "redteam_knowledge",
    "boltzmann": "redteam_knowledge",
}
"""A dependency that one package exists to encapsulate. Anyone else importing it has reached
around the boundary."""


def source_roots() -> dict[str, Path]:
    roots: dict[str, Path] = {}
    for parent in ("packages", "apps"):
        base = REPO_ROOT / parent
        if not base.is_dir():
            continue
        for src in base.glob("*/src/redteam_*"):
            if src.is_dir():
                roots[src.name] = src
    return roots


def imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            found.add(node.module.split(".")[0])
    return found


def test_every_package_is_in_the_table() -> None:
    unknown = set(source_roots()) - set(ALLOWED)
    assert not unknown, f"packages with no place in the import graph: {sorted(unknown)}"


def test_no_package_imports_outside_its_allowance() -> None:
    violations: list[str] = []
    for name, root in source_roots().items():
        allowed = ALLOWED[name] | {name}
        for path in sorted(root.rglob("*.py")):
            internal = {m for m in imported_modules(path) if m.startswith("redteam_")}
            for module in sorted(internal - allowed):
                violations.append(f"{path.relative_to(REPO_ROOT)} imports {module}")
    assert not violations, "\n".join(violations)


def test_encapsulated_dependencies_stay_encapsulated() -> None:
    violations: list[str] = []
    for name, root in source_roots().items():
        for path in sorted(root.rglob("*.py")):
            for module in imported_modules(path) & set(THIRD_PARTY_ONLY_IN):
                if THIRD_PARTY_ONLY_IN[module] != name:
                    violations.append(f"{path.relative_to(REPO_ROOT)} imports {module}")
    assert not violations, "\n".join(violations)
