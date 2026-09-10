"""`GovernedTarget`: the single door every call to the assistant goes through.

gaussia governs the search; it governs nothing operational. The budget, the pacing gate, the
safe-mode gate, retrying what the policy says will recover, and writing each exchange to the store
are all the engine's, and all of them have to happen on every call -- so rather than scattering them
through a conduction loop, they wrap the adapter.

The trick is that gaussia does not know this exists. To the `Profiler` and the `Exploiter` it is a
`TargetAssistant` like any other. Which means the governance **cannot be bypassed** -- there is no
other door -- and nothing had to be forked to install it.

**A retry happens inside one `send`.** gaussia sends one query per probe and reads one answer, and
the recorder behind this door maps the k-th answer to the k-th unit; a retry that surfaced as a
second exchange would shift every unit after it by one. So the loop is here, the Profiler sees one
exchange, and the recorder sees one -- the last attempt's.

**So does a conversation, for the same reason.** A strategy the catalogue delivers as many turns is
still one `send` to gaussia: the opening goes out, an attacker writes what to say next from what
came back, every turn passes through the same budget, pacing and retry as a single call, and gaussia
grades the final answer -- what the escalation obtained. The recorder sees one exchange carrying the
whole conversation. Which delivery a `send` gets is read by position, the way the recorder reads
which unit it closes: the k-th live exchange is the k-th planned delivery, and anything past the
plan -- the search's own conversations -- is static.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Protocol

from gaussia.core.target_assistant import TargetAssistant
from gaussia.schemas.roastme import TargetResponse

from redteam_contracts.failure import TransportFailure
from redteam_contracts.run_spec import DEFAULT_MAX_RETRIES, ConnectorSpec
from redteam_engine.errors import error_for
from redteam_engine.failure_policy import Action, policy_for
from redteam_engine.ledger import FailureLedger
from redteam_engine.planned import (
    ORDINARY_ENDS,
    AttackerProtocol,
    Conversation,
    PlannedDelivery,
    conduct_many,
    static,
)
from redteam_target.capabilities import CapabilityGate
from redteam_target.failures import failure_of


class SecretResolver(Protocol):
    """What the engine needs from the secrets backend: a reference becomes a value. The backend
    itself is the runner's to build; this package never imports it."""

    def resolve(self, ref: str) -> str: ...


class BudgetExhausted(RuntimeError):
    """The run hit its ceiling. Not a lost run: everything closed is in the store with honest
    coverage, and the consumer decides whether the partial thing is useful."""


@dataclass
class Budget:
    """Where a run stops.

    It matters more than it looks: the number of target calls is `categories x
    queries_per_category`, and the **search** decides it, not our request. A retry is a call too,
    and is charged as one: the ceiling is on what the assistant's infrastructure takes, not on what
    the plan intended.
    """

    max_target_calls: int | None = None
    max_wall_seconds: int | None = None
    started_at: float = field(default_factory=time.monotonic)
    calls: int = 0

    def charge(self) -> None:
        self.calls += 1
        if self.max_target_calls is not None and self.calls > self.max_target_calls:
            raise BudgetExhausted(f"budget of {self.max_target_calls} target calls exhausted")
        self.charge_time()

    def charge_time(self) -> None:
        """The wall clock alone, for waiting that costs the assistant nothing.

        Generation spends the run's time without touching anybody's assistant, so it is charged
        against `max_wall_seconds` and against no call count. Separated rather than overloading
        `charge`, because "how long a run may take" and "how much load somebody else's
        infrastructure takes" are two ceilings and conflating them would make a slow generation
        look like traffic.
        """
        if self.max_wall_seconds is not None:
            elapsed = time.monotonic() - self.started_at
            if elapsed > self.max_wall_seconds:
                raise BudgetExhausted(f"wall-clock budget of {self.max_wall_seconds}s exhausted")


@dataclass
class RateGate:
    """How much load somebody else's infrastructure takes, and how we back off when it says stop."""

    min_interval_seconds: float = 0.0
    backoff_base: float = 2.0
    max_backoff_seconds: float = 60.0
    sleep: Callable[[float], None] = time.sleep
    """Injectable, so a test of the backoff does not wait it out."""

    _last_call: float = 0.0
    _consecutive_failures: int = 0

    def wait(self) -> None:
        if self.min_interval_seconds <= 0:
            return
        gap = time.monotonic() - self._last_call
        if gap < self.min_interval_seconds:
            self.sleep(self.min_interval_seconds - gap)
        self._last_call = time.monotonic()

    def back_off(self, retry_after: float | None = None) -> float:
        """Wait before the next attempt. What the target asked for when it said; exponential when
        it did not; capped either way, because a `Retry-After` of an hour is a run that should
        give the unit up and let the next attempt come back, not one that stalls in silence.
        Returns the seconds waited, for the record."""
        self._consecutive_failures += 1
        exponential = self.backoff_base**self._consecutive_failures
        delay = min(
            retry_after if retry_after is not None else exponential, self.max_backoff_seconds
        )
        self.sleep(delay)
        return delay

    def note_success(self) -> None:
        self._consecutive_failures = 0


class GovernedTarget(TargetAssistant):  # type: ignore[misc]  # gaussia ships no stubs
    """A target with the gates, the budget, the retry policy and the recording attached.

    Args:
        planned: How each live unit is delivered, in the order the units reach this door. Empty
            means every exchange is static, which is what a run with no delivery sidecar is.
        attackers: The attackers the planned deliveries name, by id, already built. A delivery
            naming an id absent here is a wiring error the runner refuses before the first turn;
            reaching it here raises rather than delivering one turn in silence.
    """

    def __init__(
        self,
        inner: TargetAssistant,
        *,
        gate: CapabilityGate,
        budget: Budget,
        rate: RateGate | None = None,
        on_exchange: object = None,
        max_retries: int = DEFAULT_MAX_RETRIES,
        ledger: FailureLedger | None = None,
        planned: Sequence[PlannedDelivery] = (),
        attackers: Mapping[str, AttackerProtocol] | None = None,
    ) -> None:
        gate.assert_may_attack()  # before the first turn, not on the first failure
        self._inner = inner
        self._budget = budget
        self._rate = rate or RateGate()
        self._on_exchange = on_exchange
        self._max_retries = max_retries
        self._planned = list(planned)
        self._attackers = dict(attackers or {})
        self.ledger = ledger or FailureLedger()
        self.exchanges: list[tuple[str, TargetResponse]] = []
        """The opening and the final answer of every closed exchange. One entry per `send`, which is
        what indexes the planned deliveries."""

        self.conversations: list[Conversation] = []
        """Every closed exchange, whole."""

        self.conducted = 0
        """Exchanges delivered as a conversation rather than one turn."""

        self.ended_early = 0
        """Conducted conversations that closed for a reason that was neither the attacker's call
        nor the bound: the attacker's provider failing, or the budget running out between turns.
        Provenance, so a manifest can say how many conversations are shorter than they were meant
        to be."""

    def send(self, query: str, session_id: str | None = None) -> TargetResponse:
        planned = self._planned_next()
        if planned is None or not planned.delivery.conducted:
            response, fatal = self._exchange(query, session_id)
            conversation = static(query, response) if response is not None else None
        else:
            attacker_id = planned.delivery.attacker or ""
            attacker = self._attackers.get(attacker_id)
            if attacker is None:
                raise LookupError(
                    f"the plan delivers a unit through attacker {attacker_id!r} and no such "
                    f"attacker was built; the runner refuses this before the first turn"
                )
            conversation, fatal = conduct_many(
                query, self._exchange, planned=planned, attacker=attacker
            )
            if conversation is not None:
                self.conducted += 1
                if conversation.ended not in ORDINARY_ENDS:
                    self.ended_early += 1

        # Recorded before anything is raised -- the store is the evidence, and a run that died of a
        # 401 should show the 401 -- and recorded once, whole, whatever the delivery.
        if conversation is not None:
            self._close(conversation)
        if fatal is not None:
            raise fatal
        assert conversation is not None
        return conversation.final

    def _planned_next(self) -> PlannedDelivery | None:
        """The delivery of the exchange about to be sent: the k-th planned for the k-th live
        exchange, and none -- static -- past the plan, where the search's own conversations are."""
        index = len(self.exchanges)
        return self._planned[index] if index < len(self._planned) else None

    def _exchange(
        self, query: str, session_id: str | None
    ) -> tuple[TargetResponse | None, BaseException | None]:
        """One governed call: paced, charged, retried as the policy says, and its failures kept.

        Returns the answer the exchange ended on, and the exception the caller raises once the
        answer is recorded -- `None` when the run may continue. `None, exc` is a call that never
        reached the target: the budget ran out before its first attempt.
        """
        retries = 0
        last_failed: tuple[TargetResponse, TransportFailure] | None = None
        while True:
            try:
                self._rate.wait()
                self._budget.charge()
            except BudgetExhausted as exhausted:
                if last_failed is not None:
                    # The budget ran out between a failed attempt and its retry. The attempt still
                    # happened: it is the exchange's final answer now, recorded before the run
                    # stops, or the unit would read as never touched rather than as failed.
                    self.ledger.record(last_failed[1])
                    return last_failed[0], exhausted
                return None, exhausted
            response = self._inner.send(query, session_id)
            failure = failure_of(response)

            if failure is None:
                self._rate.note_success()
                if retries:
                    self.ledger.recovered += 1
                return response, None

            verdict = policy_for(failure.kind)
            if verdict.action is Action.RETRY and retries < self._max_retries:
                retries += 1
                last_failed = (response, failure)
                self._rate.back_off(
                    failure.retry_after_seconds if verdict.honour_retry_after else None
                )
                continue

            # Given up on, or about to abort: either way this is the exchange's final answer.
            self.ledger.record(failure)
            if verdict.action is Action.ABORT:
                return response, error_for(failure)
            return response, None

    def _close(self, conversation: Conversation) -> None:
        self.exchanges.append((conversation.opening, conversation.final))
        self.conversations.append(conversation)
        if callable(self._on_exchange):
            self._on_exchange(conversation.opening, conversation.final, conversation)


def attackable(
    connector: ConnectorSpec,
    resolver: SecretResolver,
    *,
    budget: Budget,
    on_exchange: object = None,
    ledger: FailureLedger | None = None,
    planned: Sequence[PlannedDelivery] = (),
    attackers: Mapping[str, AttackerProtocol] | None = None,
) -> GovernedTarget:
    """The only way a run gets a target: built by name, wrapped before the first turn.

    Everything the connector spec declares is honoured here and nowhere else -- the kind picks the
    adapter, the secret reference becomes a credential, the interval becomes the rate gate, the
    retry ceiling becomes the loop's, and the capability gate refuses before anything is sent. The
    conduction knows no concrete adapter class, and a guard checks that it stays that way: an
    adapter reachable without this wrapper is a budget and a safe-mode gate that can be skipped by
    accident.
    """
    from redteam_target import build_target

    credential = resolver.resolve(connector.secret_ref) if connector.secret_ref else None
    return GovernedTarget(
        build_target(connector, credential),
        gate=CapabilityGate(
            declared_capabilities=connector.declared_capabilities, safe_mode=connector.safe_mode
        ),
        budget=budget,
        rate=RateGate(min_interval_seconds=connector.min_interval_seconds),
        on_exchange=on_exchange,
        max_retries=connector.max_retries,
        ledger=ledger,
        planned=planned,
        attackers=attackers,
    )
