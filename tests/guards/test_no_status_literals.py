"""Guard: nothing on the transport surface compares a status to a number.

A transport failure is classified once, by name -- `HTTPStatus.TOO_MANY_REQUESTS`, the standard
library's `is_server_error` -- into a `TransportFailure.kind`, and everything after that reads the
kind. A literal `== 429` somewhere else is how a second, slightly different mapping grows in another
file, the two disagree, and a failure is one kind to the adapter and another to the engine. A
substring match on `"429"` against a string that never contains it is exactly how that starts.

Read off the syntax tree rather than by substring, so `status_code=201` on a route -- a keyword
argument, not a comparison -- and a docstring that mentions a status are not violations.
"""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SURFACE = ("packages/target/src", "packages/engine/src")
"""Where a status is read off a response. The dispatcher reads the platform's answers and joins
this surface once its own comparisons are spelled by name."""

STATUS_NAMES = ("status_code", "status", "code")
LOWEST_STATUS, HIGHEST_STATUS = 100, 599


def _names_a_status(node: ast.expr) -> bool:
    if isinstance(node, ast.Attribute):
        name = node.attr
    elif isinstance(node, ast.Name):
        name = node.id
    else:
        return False
    return name.endswith(STATUS_NAMES)


def _is_status_literal(node: ast.expr) -> bool:
    return (
        isinstance(node, ast.Constant)
        and isinstance(node.value, int)
        and not isinstance(node.value, bool)
        and LOWEST_STATUS <= node.value <= HIGHEST_STATUS
    )


def status_literal_comparisons(source: str) -> list[str]:
    """Every comparison in `source` between something named like a status and a literal in the
    status range, as `line: source`."""
    hits: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Compare):
            continue
        sides = [node.left, *node.comparators]
        if any(_names_a_status(side) for side in sides) and any(
            _is_status_literal(side) for side in sides
        ):
            hits.append(f"{node.lineno}: {ast.unparse(node)}")
    return sorted(hits)


def test_the_transport_surface_compares_no_status_to_a_number() -> None:
    offenders = [
        f"{path.relative_to(ROOT)}:{hit}"
        for surface in SURFACE
        if (ROOT / surface).is_dir()
        for path in sorted((ROOT / surface).rglob("*.py"))
        for hit in status_literal_comparisons(path.read_text())
    ]
    assert not offenders, (
        f"{offenders} compare a status to a literal; classify it by name in "
        f"redteam_target.failures and read the kind"
    )


def test_the_guard_sees_every_shape_of_the_comparison_and_ignores_the_rest() -> None:
    """A guard has to be checked to fail."""
    assert status_literal_comparisons("if r.status_code == 429:\n    pass\n")
    assert status_literal_comparisons("ok = 200 <= response.status < 300\n")
    assert status_literal_comparisons("if code != 404:\n    pass\n")
    assert not status_literal_comparisons("@app.post('/x', status_code=201)\ndef f(): ...\n")
    assert not status_literal_comparisons('"""a 429 is a rate limit"""\nx = 1\n')
    assert not status_literal_comparisons(
        "from http import HTTPStatus\nif r.status_code == HTTPStatus.CONFLICT:\n    pass\n"
    )
    assert not status_literal_comparisons("if count == 429:\n    pass\n")
