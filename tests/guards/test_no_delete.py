"""The store appends. Nothing in the codebase removes a key, and the interface has no way to.

A trace that can be rewritten stops supporting any claim derived from it, and so does a spec, a
probe set, an attempt, a failure record and the manifest. Append-only is the property the whole
design rests on, and the cheapest way to keep it is to have no `delete` at all: an interface with
no way to remove a key is an interface nobody has to be careful with.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DELETE_CALL = re.compile(r"\.delete\(")


def source_files() -> list[Path]:
    found: list[Path] = []
    for parent in ("packages", "apps"):
        root = REPO_ROOT / parent
        if root.is_dir():
            found.extend(root.glob("*/src/**/*.py"))
    return sorted(found)


def test_nothing_calls_delete_on_a_store() -> None:
    offenders = [
        f"{path.relative_to(REPO_ROOT)}:{number}"
        for path in source_files()
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
        if DELETE_CALL.search(line)
    ]
    assert not offenders, f"the store appends; nothing removes a key: {offenders}"


def test_the_store_interface_has_no_delete() -> None:
    from redteam_store.interface import ObjectStore
    from redteam_store.memory import MemoryObjectStore

    assert not hasattr(ObjectStore, "delete")
    assert not hasattr(MemoryObjectStore, "delete")
