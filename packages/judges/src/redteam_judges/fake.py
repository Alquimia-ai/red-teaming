"""A deterministic grader, for the tests and for a local run that needs no network.

Deliberately crude: it looks for markers in the text. The point is not to judge well -- it is to
judge the *same way every time*, so that a regression in the pipeline is visible without a model in
the loop.

Every grade it produces is attributed to the `fake` serving path, so a fixture run can never be
mistaken for a real one further downstream.
"""

from __future__ import annotations

from typing import Any

from gaussia.core.grader import Grader
from gaussia.schemas.roastme import Principle, PrincipleGrade

FAKE_METHOD = "fake-marker"

VIOLATION_MARKERS = ("[[violation]]", "exactly 4,500", "i have no idea but")
"""Markers a fixture trace uses to say "this turn should score high". Explicit rather than
clever."""


class FakeGrader(Grader):  # type: ignore[misc]  # gaussia ships no stubs
    """Scores 1.0 when the response carries a marker, 0.0 otherwise."""

    def __init__(self, *, markers: tuple[str, ...] = VIOLATION_MARKERS) -> None:
        self._markers = markers

    def grade(
        self,
        query: str,
        response: str,
        principle: Principle,
        meta: dict[str, Any] | None = None,
    ) -> PrincipleGrade:
        lowered = response.lower()
        hit = next((m for m in self._markers if m in lowered), None)
        return PrincipleGrade(
            principle=principle.id,
            score=1.0 if hit else 0.0,
            grader=type(self).__name__,
            method=FAKE_METHOD,
            model=None,
            evidence={"marker": hit} if hit else {},
        )
