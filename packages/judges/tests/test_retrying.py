"""A verdict that did not arrive is asked for again, and a run out of attempts fails loudly."""

from __future__ import annotations

from typing import Any

import pytest
from gaussia.core.exceptions import LogprobsExtractionError
from gaussia.schemas.roastme import Principle, PrincipleGrade

from redteam_judges.fake import FakeGrader
from redteam_judges.retrying import RetryingGrader

PRINCIPLE = Principle(id="p", weight=1.0, rubric="rubric", grader=FakeGrader())


class _Flaky:
    """Truncates the first `failures` verdicts, then answers. What a reasoning model at the edge of
    its budget looks like from the outside."""

    def __init__(self, failures: int) -> None:
        self.failures = failures
        self.calls = 0

    def grade(self, query: str, response: str, principle: Principle, meta: Any = None) -> Any:
        self.calls += 1
        if self.calls <= self.failures:
            raise LogprobsExtractionError("no token of ('YES', 'NO') in the sequence")
        return PrincipleGrade(
            principle=principle.id, score=1.0, grader="flaky", method="logprob", model=None
        )


def test_a_truncated_verdict_is_asked_for_again() -> None:
    """The reasoning length is a random draw per call, so asking again is asking a fresh draw."""
    inner = _Flaky(failures=1)
    grade = RetryingGrader(inner, attempts=3).grade("q", "a", PRINCIPLE)
    assert grade.score == 1.0
    assert inner.calls == 2


def test_running_out_of_attempts_raises_the_last_failure() -> None:
    """Three truncations running is a budget the model needs raised, not luck. It is not papered
    over with a sampled verdict, which would be a different instrument answering under the same
    name."""
    with pytest.raises(LogprobsExtractionError):
        RetryingGrader(_Flaky(failures=5), attempts=3).grade("q", "a", PRINCIPLE)


def test_how_many_verdicts_needed_a_retry_is_recorded() -> None:
    """Provenance rather than a metric: a run where most verdicts were retried is measuring a judge
    at the edge of its budget."""
    inner = _Flaky(failures=1)
    retrying = RetryingGrader(inner, attempts=3)
    retrying.grade("q", "a", PRINCIPLE)
    retrying.grade("q", "a", PRINCIPLE)
    assert retrying.retried == 1


def test_a_grade_needs_at_least_one_attempt() -> None:
    with pytest.raises(ValueError, match="at least one attempt"):
        RetryingGrader(FakeGrader(), attempts=0)
