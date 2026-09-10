"""The webhook: a pointer into the store, delivered a bounded number of times.

The store is the truth and the webhook is a courtesy: it says "the run closed, read this key" or
"this attempt died, read this record", and a consumer that misses one polls the status and reads
the same thing. So there is no case where losing a webhook changes the result -- which is what buys
the absence of a queue, a dead-letter store and a second process.

What it still owes the consumer is a fair try and an honest answer. So: bounded retries with
backoff, an idempotency key a receiver can deduplicate on, and a typed outcome rather than a bare
boolean, so the caller can log "undelivered" beside the run rather than guessing. Nothing here
retries forever and nothing queues: a delivery that does not land after its attempts is reported as
undelivered, and the store still holds everything the payload pointed at.
"""

from __future__ import annotations

import hashlib
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import httpx

TIMEOUT = 10.0
"""How long one attempt waits. A consumer's webhook is not on the critical path of anything it does,
so a slow receiver is retried rather than waited on."""

ATTEMPTS = 5
"""How many times a delivery is tried before it is reported undelivered.

Five, with the backoff below, spans about half a minute -- long enough to ride out a receiver
restart or a proxy blip, short enough that a job does not sit on a dead endpoint. Bounded on
purpose: a delivery that retried forever would be a job nobody can tell from a hung one, and the
undelivered answer is useful precisely because it arrives."""

BACKOFF = 2.0
"""Seconds before the second attempt, doubling. The receiver is somebody else's infrastructure and
a tight loop against a struggling one is an attack, not a retry."""


class Delivery:
    """What became of one delivery. `Delivered`, `Undelivered` or `NotAsked`, never a bare
    boolean."""


@dataclass(frozen=True)
class Delivered(Delivery):
    """The receiver acknowledged it."""

    attempts: int
    status: int


@dataclass(frozen=True)
class NotAsked(Delivery):
    """The run declared no webhook, so there was nothing to deliver and nobody to deliver it to.

    Its own outcome rather than a `Delivered` with zero attempts: "nobody was told" and "somebody
    was told" are different facts about a run, and a log line has to be able to say which.
    """


@dataclass(frozen=True)
class Undelivered(Delivery):
    """It did not land. The store still holds everything the payload pointed at.

    `why` is the last attempt's reason, not a summary of all of them: a receiver that answers 503
    five times has one problem, and listing it five times would not help anybody.
    """

    attempts: int
    why: str


def idempotency_key(run_id: str, phase: str) -> str:
    """One key per thing that can be delivered, stable across every retry of it.

    Derived rather than random, so a retry after a lost acknowledgement carries the same key the
    first attempt did -- which is the whole point: the receiver can tell "the same delivery again"
    from "a second delivery", and a run whose outcome arrives twice is stored once.

    `(run_id, phase)` because that is what identifies a delivery: one run reports closing once and
    an attempt dying once, and those are different things to have received.
    """
    return hashlib.sha256(f"{run_id}:{phase}".encode()).hexdigest()[:32]


def deliver(
    url: str | None,
    payload: dict[str, Any],
    *,
    key: str,
    attempts: int = ATTEMPTS,
    sleep: Callable[[float], None] | None = None,
    client: httpx.Client | None = None,
) -> Delivery:
    """Send it, retrying a bounded number of times, and say what became of it.

    Args:
        url: Where to send it. `None` answers `NotAsked`.
        payload: What to send, as JSON.
        key: The idempotency key, echoed in a header so a receiver can deduplicate.
        attempts: How many tries. `1` disables retrying.
        sleep: Injectable, so a test of the backoff does not wait it out. Resolved at call time
            rather than bound as a default, because a default is captured when the function is
            defined -- which makes it unpatchable, and a suite that waits out real backoff is a
            suite people stop running.
        client: Injectable, for the same reason.

    **This never raises.** A caller in the middle of closing a run cannot be made to handle a
    transport error from the last thing it does, and an exception here would turn a closed run into
    a failed attempt.
    """
    if not url:
        return NotAsked()

    owned = client is None
    http = client or httpx.Client(timeout=TIMEOUT)
    pause = sleep or time.sleep
    why = "no attempt was made"
    try:
        for attempt in range(1, max(attempts, 1) + 1):
            why = _attempt(http, url, payload, key)
            if why == "":
                return Delivered(attempts=attempt, status=200)
            if attempt < attempts:
                pause(BACKOFF * (2 ** (attempt - 1)))
    finally:
        if owned:
            http.close()
    return Undelivered(attempts=max(attempts, 1), why=why)


def _attempt(http: httpx.Client, url: str, payload: dict[str, Any], key: str) -> str:
    """One try. Empty string means it landed; anything else is why it did not.

    A string rather than an exception because every outcome here is ordinary -- a receiver
    restarting, a proxy in front of it, a name that does not resolve yet -- and raising would make
    the caller write the same `except` this already is.
    """
    try:
        answered = http.post(url, json=payload, headers={"Idempotency-Key": key}, timeout=TIMEOUT)
    except Exception as unreachable:
        return f"{type(unreachable).__name__}: {str(unreachable)[:200]}"
    if answered.is_success:
        return ""
    return f"the receiver answered {answered.status_code}"
