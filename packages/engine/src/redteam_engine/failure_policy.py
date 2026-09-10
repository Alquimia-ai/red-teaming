"""What the engine does about a kind of transport failure. Data, keyed by kind, never an `if`.

The target adapter says what happened (`TransportFailure.kind`); this says what to do about it, and
the two are kept apart on purpose. An adapter that decided to retry would be an adapter that talks
to the assistant more than the plan says, outside the budget and the rate gate; an engine that
decided what a 429 *is* would be a second copy of the mapping. So the adapter classifies, and the
governed door asks this table.

Three answers exist. **Retry**: the same probe, after backing off, up to the run's `max_retries` --
for a failure that says the channel will recover. **Give up**: the unit is marked failed and left
pending for the next attempt -- for a failure that repeating the request would not change.
**Abort**: the run stops, with the kind's own exception -- for a failure that makes every further
call a wasted attack on the assistant, which is what a refused credential is.

A kind nothing registered a policy for is given up on. That is the honest default: a failure we do
not understand is not one we should keep paying somebody else's infrastructure to reproduce.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from redteam_contracts.failure import (
    CLIENT_ERROR,
    EMPTY_RESPONSE,
    MALFORMED_RESPONSE,
    NETWORK,
    RATE_LIMITED,
    SERVER_ERROR,
    TIMEOUT,
    UNAUTHORIZED,
    UNKNOWN,
    UPSTREAM_UNAVAILABLE,
)


class Action(StrEnum):
    RETRY = "retry"
    GIVE_UP = "give_up"
    ABORT = "abort"


@dataclass(frozen=True)
class Verdict:
    action: Action
    honour_retry_after: bool = False
    """Whether the target's own `Retry-After`, when it sent one, sets the delay before the retry.
    Only meaningful for `RETRY`; the exponential backoff applies otherwise."""


RETRY_AS_ASKED = Verdict(Action.RETRY, honour_retry_after=True)
RETRY_BACKING_OFF = Verdict(Action.RETRY)
GIVE_UP = Verdict(Action.GIVE_UP)
ABORT = Verdict(Action.ABORT)

_POLICIES: dict[str, Verdict] = {}


def register_policy(kind: str, verdict: Verdict) -> None:
    """Decide what a kind of failure gets. Re-registering the same verdict is a no-op; a different
    one under a known kind is refused, so two modules cannot quietly disagree about a 429."""
    existing = _POLICIES.get(kind)
    if existing is not None:
        if existing == verdict:
            return
        raise ValueError(
            f"failure kind {kind!r} already has a policy ({existing.action.value}); exactly one "
            f"per kind, or the engine's behaviour depends on import order"
        )
    _POLICIES[kind] = verdict


def policy_for(kind: str) -> Verdict:
    """The verdict for a kind, `GIVE_UP` for one nobody registered."""
    return _POLICIES.get(kind, GIVE_UP)


def registered_policies() -> dict[str, Verdict]:
    return dict(_POLICIES)


register_policy(RATE_LIMITED, RETRY_AS_ASKED)
register_policy(UPSTREAM_UNAVAILABLE, RETRY_BACKING_OFF)
register_policy(SERVER_ERROR, RETRY_BACKING_OFF)
register_policy(TIMEOUT, RETRY_BACKING_OFF)
register_policy(NETWORK, RETRY_BACKING_OFF)
register_policy(UNAUTHORIZED, ABORT)
register_policy(CLIENT_ERROR, GIVE_UP)
register_policy(MALFORMED_RESPONSE, GIVE_UP)
register_policy(EMPTY_RESPONSE, GIVE_UP)
register_policy(UNKNOWN, GIVE_UP)
