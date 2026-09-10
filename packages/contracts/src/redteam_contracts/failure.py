"""A transport failure, as a record rather than as a class name.

A target adapter that reports a failed exchange as `type(error).__name__` turns a 429 into
`"HTTPStatusError"`, the same string as a 500 or a 404, and everything downstream that wants to know
what happened -- the rate gate deciding whether to back off, the record of why an attempt died, a
reader of the evidence -- is left with a word that names a Python class.

This is the record the target adapter produces instead. Facts only: what kind of failure, the
status if there was one, what the target asked for, what it said, what raised. What to *do* about
it is a policy and lives with the engine; whether it is retryable is not a property of the failure
but of the run, and is not written here.

**The kind is a string, not an enum.** The kinds below are the ones the shipped classifiers produce,
and an adapter reaching a target through some other channel may register a kind this contract has
never heard of; the policy answers an unknown kind with the honest default rather than refusing it.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

RATE_LIMITED = "rate_limited"
"""The target asked for less load. The one failure that says exactly what to do about it."""

UNAUTHORIZED = "unauthorized"
"""The target refused the credential. Every further call is a wasted attack on the assistant."""

UPSTREAM_UNAVAILABLE = "upstream_unavailable"
"""Something between here and the assistant is down: a gateway, a proxy, a saturated service."""

SERVER_ERROR = "server_error"
"""The target's side failed to answer, for a reason it did not name."""

CLIENT_ERROR = "client_error"
"""The target says the request itself was wrong. Repeating it changes nothing."""

TIMEOUT = "timeout"
NETWORK = "network"
MALFORMED_RESPONSE = "malformed_response"
"""An answer arrived and could not be read as one: not JSON, or JSON of the wrong shape."""

EMPTY_RESPONSE = "empty_response"
"""An answer arrived and said nothing. Graded as compliance, this is how an outage becomes a clean
bill of health."""

UNKNOWN = "unknown"
"""Nothing registered recognised the error. Carried with its class name, so the reader still can."""


class TransportFailure(BaseModel):
    """What a failed exchange with the target actually was."""

    model_config = ConfigDict(frozen=True)

    kind: str
    message: str
    """What the target or the transport said, short. A body's `error.message`, an HTTP phrase, an
    exception's text."""

    error_type: str
    """The exception class that raised, or the runtime's own status word. Provenance for the
    reader, never the thing a decision is made on."""

    status: int | None = None
    retry_after_seconds: float | None = None
    """What the target asked for, when it said. Read off `Retry-After`, seconds or an HTTP date."""

    def summary(self) -> str:
        """One line for `failure_reason`, kind first, so a log is readable without the record."""
        detail = self.message
        if self.status is not None:
            detail = f"HTTP {self.status} {detail}".rstrip()
        if self.retry_after_seconds is not None:
            detail = f"{detail}, retry after {self.retry_after_seconds:g}s"
        return f"{self.kind}: {detail}"
