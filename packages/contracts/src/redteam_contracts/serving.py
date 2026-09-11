"""Where a model ran, as the provenance records it.

The same model exposes a token distribution through one serving path and not through another, and
a grader that reads logprobs behaves differently from one that has to vote across samples. Same
model, two kinds of number. Recording where a model was served is what keeps two runs from looking
comparable when they are not.
"""

from __future__ import annotations

from enum import StrEnum


class ServingPath(StrEnum):
    """Where a model ran. Part of the instrument, not a deployment detail."""

    HOSTED_API = "hosted_api"
    SELF_HOSTED = "self_hosted"
    FAKE = "fake"
    """A deterministic stand-in. Present so a fixture run can never be mistaken for a real one."""
