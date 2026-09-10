"""Every workspace member has a commit scope, and every scope the docs promise exists.

Releases are cut per app and attributed through commit scopes, so a member that commitlint does not
know is a member whose changes cannot be attributed. The enum lives in `commitlint.config.js`;
this guard reads it back rather than duplicating the list.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG = REPO_ROOT / "commitlint.config.js"
CROSS_CUTTING = frozenset({"deploy", "docs", "ci", "deps", "repo", "skills"})


def scope_enum() -> frozenset[str]:
    text = CONFIG.read_text(encoding="utf-8")
    block = re.search(r'"scope-enum":\s*\[\s*2,\s*"always",\s*\[(.*?)\]\s*,?\s*\]', text, re.S)
    assert block, "commitlint.config.js has no scope-enum rule"
    return frozenset(re.findall(r'"([a-z0-9-]+)"', block[1]))


def member_names() -> set[str]:
    names: set[str] = set()
    for parent in ("apps", "packages"):
        root = REPO_ROOT / parent
        if not root.is_dir():
            continue
        names.update(p.name for p in root.iterdir() if (p / "pyproject.toml").is_file())
    return names


def test_every_workspace_member_has_a_scope() -> None:
    missing = member_names() - scope_enum()
    assert not missing, f"workspace members without a commit scope: {sorted(missing)}"


def test_cross_cutting_scopes_exist() -> None:
    missing = CROSS_CUTTING - scope_enum()
    assert not missing, f"cross-cutting scopes missing from commitlint: {sorted(missing)}"


def test_scope_is_mandatory() -> None:
    text = CONFIG.read_text(encoding="utf-8")
    assert re.search(r'"scope-empty":\s*\[\s*2,\s*"never"\s*\]', text), "scope must be mandatory"
