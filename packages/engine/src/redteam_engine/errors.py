"""The exceptions a run dies with when the channel to the target is what failed.

One base, one subclass per kind that deserves its own name, and a registry from kind to class so
raising is always `raise error_for(failure)` and never a chain of `if kind == ...`. A kind nobody
registered an exception for is raised as the base class, which still carries the record.

Why typed at all: the failure record an attempt leaves (`runs/{id}/failures/{attempt}.json`) could
say `ProfileTooThin: 31 of 40 exchanges could not be graded`. True, and useless -- the reader would
still have to open thirty-one traces to learn that every one of them was a 401. The record says
`unauthorized` instead, with the status and what the target said, and the reader knows which
credential to fix before relaunching.
"""

from __future__ import annotations

from redteam_contracts.failure import (
    EMPTY_RESPONSE,
    MALFORMED_RESPONSE,
    NETWORK,
    RATE_LIMITED,
    SERVER_ERROR,
    TIMEOUT,
    UNAUTHORIZED,
    UPSTREAM_UNAVAILABLE,
    TransportFailure,
)


class TargetFailure(RuntimeError):
    """The channel to the target failed in a way the run could not continue through.

    Carries the record, so whatever catches it -- the attempt's failure record, a log line -- can
    say what the target actually answered rather than what Python class raised.
    """

    def __init__(self, failure: TransportFailure, message: str | None = None) -> None:
        super().__init__(message or failure.summary())
        self.failure = failure
        self.kind = failure.kind


class TargetRateLimited(TargetFailure):
    """The target kept asking for less load past every retry the run allowed."""


class TargetUnauthorized(TargetFailure):
    """The target refused the credential. Nothing about the assistant was measured, and nothing
    more should be sent until the reference the spec names resolves to a key it accepts."""


class TargetUnreachable(TargetFailure):
    """Timeouts, connection errors, a gateway that never answered: the channel, not the
    assistant."""


class TargetServerError(TargetFailure):
    """The target's side failed without saying why, and kept failing."""


class TargetMalformed(TargetFailure):
    """The target answered, and what it answered could not be read as an answer."""


_ERRORS: dict[str, type[TargetFailure]] = {}


def register_error(kind: str, error: type[TargetFailure]) -> None:
    existing = _ERRORS.get(kind)
    if existing is not None:
        if existing is error:
            return
        raise ValueError(
            f"failure kind {kind!r} already raises {existing.__name__}; exactly one exception per "
            f"kind, or the same outage is reported under two names"
        )
    _ERRORS[kind] = error


def error_for(failure: TransportFailure, message: str | None = None) -> TargetFailure:
    """The exception registered for the failure's kind, built around the record."""
    return _ERRORS.get(failure.kind, TargetFailure)(failure, message)


register_error(RATE_LIMITED, TargetRateLimited)
register_error(UNAUTHORIZED, TargetUnauthorized)
register_error(UPSTREAM_UNAVAILABLE, TargetUnreachable)
register_error(TIMEOUT, TargetUnreachable)
register_error(NETWORK, TargetUnreachable)
register_error(SERVER_ERROR, TargetServerError)
register_error(MALFORMED_RESPONSE, TargetMalformed)
register_error(EMPTY_RESPONSE, TargetMalformed)
