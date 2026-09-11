"""The repository speaks one vocabulary, and a few words are not part of it.

Every tracked file -- content and path -- is scanned for terms that must not appear anywhere in
this codebase: names of unrelated projects and organisations, and words that describe this
repository as derived from somewhere else rather than as the origin of its own architecture. The
list is deliberately short and deliberately spelled as regular expressions, so that the Python
keyword `yield` (a bare word followed by a value or a newline) is never confused with a project
name spelled with a separator or a capital.

The guard reads `git ls-files` rather than walking the tree so that ignored files -- virtual
environments, caches, the operator workspace -- cannot trip it or hide behind it.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

FORBIDDEN: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("unrelated organisation", re.compile(r"(?i)ethi(compass|batch|dataset)")),
    ("unrelated project, as an identifier", re.compile(r"\b[Yy]ield[_-][a-z]")),
    ("unrelated project, as a word", re.compile(r"\bYield\b")),
    ("unrelated project, as an env prefix", re.compile(r"\bYIELD_")),
    ("unrelated project, as a directory", re.compile(r"\.yield\b")),
    ("unrelated downstream component", re.compile(r"\bLens\b")),
    ("unrelated downstream component", re.compile(r"\bSteward\b")),
    (
        "this repository is the origin, not a destination",
        re.compile(r"(?i)\bmigrat(e|ed|es|ion|ions|ing)\b"),
    ),
)

# Files the scan skips: the guard itself (it spells the patterns), and generated lockfiles whose
# contents are third-party metadata rather than this repository's prose.
EXCLUDED = frozenset(
    {
        "tests/guards/test_vocabulary.py",
        "uv.lock",
        "package-lock.json",
    }
)


def tracked_files() -> list[Path]:
    listed = subprocess.run(
        ["git", "ls-files", "-z"], cwd=REPO_ROOT, check=True, capture_output=True
    ).stdout
    return [Path(p) for p in listed.decode().split("\0") if p and p not in EXCLUDED]


def violations_in(relative: Path) -> list[str]:
    found: list[str] = []
    for label, pattern in FORBIDDEN:
        if pattern.search(str(relative)):
            found.append(f"{relative}: path matches {pattern.pattern!r} ({label})")
    path = REPO_ROOT / relative
    if not path.is_file():
        return found
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return found  # binary: nothing to read
    for number, line in enumerate(text.splitlines(), 1):
        for label, pattern in FORBIDDEN:
            if pattern.search(line):
                found.append(f"{relative}:{number}: {pattern.pattern!r} ({label}): {line.strip()}")
    return found


def test_no_forbidden_vocabulary_in_tracked_files() -> None:
    files = tracked_files()
    assert files, "git ls-files returned nothing; the guard must run inside the repository"
    violations = [v for relative in files for v in violations_in(relative)]
    assert not violations, "forbidden vocabulary:\n" + "\n".join(violations)


@pytest.mark.parametrize(
    "allowed",
    [
        "def gen():\n    yield value\n",
        "    yield\n",
        "yields a probe set",
        "the high-yield strategy",
    ],
)
def test_the_python_keyword_and_the_english_word_are_allowed(allowed: str) -> None:
    assert not [label for label, pattern in FORBIDDEN if pattern.search(allowed)]


@pytest.mark.parametrize(
    "forbidden",
    [
        "yield_store",
        "yield-api",
        "Yield does",
        "YIELD_STORE_BACKEND",
        ".yield/runs",
        "Migration guide",
    ],
)
def test_the_project_name_forms_are_caught(forbidden: str) -> None:
    assert [label for label, pattern in FORBIDDEN if pattern.search(forbidden)]
