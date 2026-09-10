"""Retrying a verdict that did not arrive, before recording that it did not.

gaussia's `LogprobGrader` names the case this exists for. When the provider answers with logprobs
and no verdict token among them -- a reasoning model that spent its budget before `YES` or `NO` --
the call worked and only this response is unusable. That is not a reason to change estimator, so
the grader raises `LogprobsExtractionError` and says, in its own docstring, that "a retrying
grader wrapped around this one" is what recovers it.

**Why a retry is the right first move.** The reasoning length is a random draw per call, so a
truncation is a tail event on this call rather than a fact about the input, and asking again is
asking a fresh draw. It is not a fix for a budget that is simply too small -- that fails every draw
-- and it is bounded, because a model that truncates three times in a row is telling you the
budget, not luck.

**What is not retried.** A provider that has settled on refusing logprobs raises before it calls
anything, so retrying it costs nothing and gains nothing; the attempts run out immediately and the
same refusal propagates. What must never happen is a retry substituting the sampling estimator for
the logprob one: that would be a different instrument answering under the same name, and the
`require_logprobs` flag exists to make that impossible.
"""

from __future__ import annotations

from typing import Any

from gaussia.core.exceptions import LogprobsExtractionError, LogprobsNotSupportedError
from gaussia.core.grader import Grader
from gaussia.schemas.roastme import Principle, PrincipleGrade

DEFAULT_ATTEMPTS = 3
"""Three draws. A verdict that truncates three times running at a budget of twice the observed
maximum is not the tail of the distribution; it is a budget the model needs raised."""

_RETRIED = (LogprobsExtractionError, LogprobsNotSupportedError)


class RetryingGrader(Grader):  # type: ignore[misc]  # gaussia ships no stubs
    """A grader that asks again when the verdict did not arrive, and gives up loudly.

    Args:
        inner: The grader whose verdicts are retried. Its estimator decision is its own and this
            never touches it.
        attempts: How many draws a verdict gets before the failure is recorded rather than retried.
    """

    def __init__(self, inner: Grader, *, attempts: int = DEFAULT_ATTEMPTS) -> None:
        if attempts < 1:
            raise ValueError(f"a grade needs at least one attempt, got {attempts}")
        self._inner = inner
        self._attempts = attempts
        self.retried = 0
        """How many verdicts needed more than one draw. Provenance rather than a metric -- a run
        where most verdicts were retried is measuring a judge at the edge of its budget."""

    @property
    def inner(self) -> Grader:
        return self._inner

    def grade(
        self,
        query: str,
        response: str,
        principle: Principle,
        meta: dict[str, Any] | None = None,
    ) -> PrincipleGrade:
        last: Exception | None = None
        for attempt in range(self._attempts):
            try:
                grade: PrincipleGrade = self._inner.grade(query, response, principle, meta)
            except _RETRIED as failed:
                last = failed
                continue
            if attempt:
                self.retried += 1
            return grade
        assert last is not None
        raise last
