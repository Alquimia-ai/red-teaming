"""Deliver static probes or attacker-steered conversations as one exchange.

Every turn passes through the governed target budget and pacing. Gaussia grades the final answer;
recording preserves all turns and the stopping reason. Planned delivery is supplied explicitly.
An interrupted conversation retains its evidence before any fatal error propagates."""

from __future__ import annotations

import secrets
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from gaussia.schemas.roastme import TargetResponse

from redteam_contracts.plan import WorkUnit
from redteam_contracts.trace import TraceLabels
from redteam_store.delivery import STATIC, Delivery, Objective

STATIC_TECHNIQUE = "static"
"""The delivery every strategy has unless the sidecar says otherwise: the query is sent, the answer
is read."""

MANY_TURNS = "many-turns"
"""A conversation opened by the probe's query and steered by an attacker toward the plugin's
objective."""

SCRIPTED_TURNS = "scripted-multi-turn"

ATTACKER_ATTEMPTS = 3
"""How many times the attacker is asked for a turn before the conversation closes without it.

Three, the number `RetryingGrader` settled on: a provider that fails three times running is telling
you something about the model rather than about luck, and every attempt is a paid request.
"""

ATTACKER_BACKOFF = 1.0
"""Seconds before the second attempt, doubling."""

ENDED_BY_ATTACKER = "attacker"
"""The attacker judged the objective reached, or finally refused."""

ENDED_BY_BOUND = "bound"
"""`max_turns` agent turns were answered."""

ENDED_BY_TARGET_FAILURE = "target_failure"
"""The target failed a turn past every retry; the unit is marked failed, as a static one would
be."""

ENDED_BY_ATTACKER_FAILURE = "attacker_failure"
"""The attacker's provider failed every attempt; the conversation closed with what it had."""

ENDED_BY_BUDGET = "budget"
"""The run's budget ran out between turns; the conversation closed with what it had, and the run
stopped."""

ORDINARY_ENDS = frozenset({ENDED_BY_ATTACKER, ENDED_BY_BOUND})
"""The two ways a conducted conversation ends on its own terms. Every other end is early."""


class AttackerProtocol(Protocol):
    """The attacker as the door sees it: something that writes the next user turn, and says which
    model it is for the record. `redteam_engine.attacker.Attacker` is the one the run builds; a
    rehearsal hands in a scripted one."""

    @property
    def model(self) -> str: ...

    def next_turn(
        self,
        objective: Objective,
        approach: Sequence[str],
        transcript: Sequence[tuple[str, str]],
    ) -> str | None: ...


Exchange = Callable[[str, str | None], tuple[TargetResponse | None, BaseException | None]]
"""One governed call to the target: the answer it gave after every retry the policy allowed, and the
exception the caller has to raise once it has recorded what happened. `None, exc` is a call that
never reached the target -- the budget ran out before the first attempt."""


@dataclass(frozen=True)
class PlannedDelivery:
    """How one live unit is delivered, decided before the first turn."""

    delivery: Delivery
    objective: Objective | None
    """What the attacker is told to obtain: the plugin's own words. `None` for a static delivery."""

    approach: tuple[str, ...] = ()
    """The strategy's description as gaussia put it on the probe -- its attributes -- so the
    attacker knows how the conversation opened."""

    script: tuple[str, ...] = ()
    """Resolved user messages for a scripted conversation, including its opening."""


@dataclass(frozen=True)
class Conversation:
    """Everything one `send` said and heard, in order: one pair for a static delivery, several for a
    conducted one. What the recorder writes as one trace."""

    pairs: tuple[tuple[str, TargetResponse], ...]
    technique: str
    attacker: str | None = None
    session_id: str | None = None
    ended: str | None = None

    @property
    def opening(self) -> str:
        return self.pairs[0][0]

    @property
    def final(self) -> TargetResponse:
        return self.pairs[-1][1]

    @property
    def depth(self) -> int:
        """How many times the agent answered."""
        return len(self.pairs)


def static(query: str, response: TargetResponse) -> Conversation:
    return Conversation(
        pairs=((query, response),), technique=STATIC_TECHNIQUE, session_id=response.session_id
    )


def planned_deliveries(
    live: Sequence[WorkUnit],
    probes: Mapping[str, Mapping[str, Any]],
    deliveries: Mapping[str, Delivery],
    objectives: Mapping[str, Objective],
) -> list[PlannedDelivery]:
    """How each live unit is delivered, in the order the units will reach the target.

    The caller binds each delivery to its unit before profiling begins.

    Raises:
        ValueError: A conducted strategy attacks nothing -- a control -- so there is no objective to
            steer toward. Publishing refuses this too; here is where the run would otherwise find
            out, and it must not find out after the first turn.
    """
    planned: list[PlannedDelivery] = []
    for unit in live:
        probe = probes.get(unit.probe_id, {})
        delivery = _delivery_of(unit, probes, deliveries)
        if not delivery.conducted:
            planned.append(PlannedDelivery(delivery=STATIC, objective=None))
            continue
        if delivery.scripted:
            messages = tuple(str(m) for m in probe.get("meta", {}).get("interaction_messages", ()))
            if len(messages) < 2:
                raise ValueError(
                    f"strategy {probe.get('strategy')!r} declares scripted delivery without at "
                    "least two resolved messages"
                )
            planned.append(PlannedDelivery(delivery=delivery, objective=None, script=messages))
            continue
        plugin = probe.get("plugin")
        objective = objectives.get(str(plugin)) if plugin else None
        if objective is None:
            raise ValueError(
                f"strategy {probe.get('strategy')!r} is delivered as a conversation and names no "
                f"plugin the run knows, so there is no objective to steer it toward; a control is "
                f"one turn, and a conducted strategy has to attack something"
            )
        planned.append(
            PlannedDelivery(
                delivery=delivery,
                objective=objective,
                approach=tuple(str(a) for a in probe.get("attrs", ())),
            )
        )
    return planned


def _delivery_of(
    unit: WorkUnit, probes: Mapping[str, Mapping[str, Any]], deliveries: Mapping[str, Delivery]
) -> Delivery:
    probe = probes.get(unit.probe_id, {})
    return deliveries.get(str(probe.get("strategy", "")), STATIC)


def attackers_named_by(
    units: Sequence[WorkUnit],
    probes: Mapping[str, Mapping[str, Any]],
    deliveries: Mapping[str, Delivery],
) -> frozenset[str]:
    """The attacker ids the plan's units are delivered through -- the whole plan, not this attempt's
    live tail.

    Provenance is about the run: an attacker that steered a conversation an earlier attempt closed
    took part in the run whether or not this attempt conducts anything, and the manifest has to
    name it. The spec is frozen, so the model bound to the id is the same model that steered then.
    """
    return frozenset(
        attacker
        for unit in units
        if (attacker := _delivery_of(unit, probes, deliveries).attacker) is not None
    )


def conducted_plugins(
    units: Sequence[WorkUnit],
    probes: Mapping[str, Mapping[str, Any]],
    deliveries: Mapping[str, Delivery],
) -> frozenset[str]:
    """The plugins whose objective an attacker will be told: those of the conducted units, and no
    others. Empty for a static run, which then reads no objective at all -- and is never asked to
    reconcile two catalogues' descriptions of a plugin nobody steers toward."""
    return frozenset(
        str(plugin)
        for unit in units
        if _delivery_of(unit, probes, deliveries).conducted
        and (plugin := probes.get(unit.probe_id, {}).get("plugin"))
    )


def delivery_provenance(
    replayed: Iterable[TraceLabels], *, conducted: int, ended_early: int
) -> dict[str, str]:
    """How many of the run's conversations were conducted and how many ended early, over the whole
    run: the traces an earlier attempt closed and this attempt replayed, plus what this attempt's
    door conducted.

    Read off the replayed traces' labels rather than remembered, because the manifest describes the
    run and an attempt that saved a conducted trace and died before the dataset left no other
    record of it. Counted from this attempt's door alone, a relaunch would report zero
    conversations and conceal the one that ended early.
    """
    for labels in replayed:
        if labels.orchestration_technique not in {MANY_TURNS, SCRIPTED_TURNS}:
            continue
        conducted += 1
        if labels.ended not in ORDINARY_ENDS:
            ended_early += 1
    return {"delivery_conducted": str(conducted), "delivery_ended_early": str(ended_early)}


def conduct_many(
    opening: str,
    exchange: Exchange,
    *,
    planned: PlannedDelivery,
    attacker: AttackerProtocol,
    attempts: int = ATTACKER_ATTEMPTS,
    backoff: float = ATTACKER_BACKOFF,
    sleep: Callable[[float], None] | None = None,
    mint: Callable[[], str] | None = None,
) -> tuple[Conversation | None, BaseException | None]:
    """One conversation: the opening, then what the attacker writes, until something ends it.

    Every turn goes through `exchange`, so it is charged, paced and retried like any call. The
    session follows gaussia's protocol for an adapter that keeps them: the opening is sent with
    none, every later turn with the one the previous answer named -- or one minted here when the
    adapter named none, so a stateless adapter that keeps its own history has a key to keep it
    under.

    Returns the conversation as it stands and the exception to raise once it is recorded, either of
    which may be `None`: no conversation when the very first call never reached the target, no
    exception when the conversation ended on its own terms.
    """
    assert planned.objective is not None and planned.delivery.attacker is not None
    pause = sleep or time.sleep
    pairs: list[tuple[str, TargetResponse]] = []
    session: str | None = None
    query = opening
    ended = ENDED_BY_BOUND
    fatal: BaseException | None = None

    while True:
        response, fatal = exchange(query, session)
        if response is None:
            # The budget ran out before this turn was sent. Nothing new happened; what did is
            # closed as it stands, and the caller raises what it was handed.
            ended = ENDED_BY_BUDGET
            break
        pairs.append((query, response))
        session = response.session_id or session or (mint or _mint)()
        if fatal is not None or response.failed:
            ended = ENDED_BY_TARGET_FAILURE
            break
        if len(pairs) >= planned.delivery.max_turns:
            ended = ENDED_BY_BOUND
            break
        transcript = [(q, r.content) for q, r in pairs]
        next_turn, asked = _next_turn(
            attacker, planned, transcript, attempts=attempts, backoff=backoff, pause=pause
        )
        if not asked:
            ended = ENDED_BY_ATTACKER_FAILURE
            break
        if next_turn is None:
            ended = ENDED_BY_ATTACKER
            break
        query = next_turn

    if not pairs:
        return None, fatal
    return (
        Conversation(
            pairs=tuple(pairs),
            technique=MANY_TURNS,
            attacker=planned.delivery.attacker,
            session_id=session,
            ended=ended,
        ),
        fatal,
    )


def conduct_scripted(
    opening: str,
    exchange: Exchange,
    *,
    planned: PlannedDelivery,
    mint: Callable[[], str] | None = None,
) -> tuple[Conversation | None, BaseException | None]:
    """Send a fixed script in one session; every message uses the governed exchange."""
    if not planned.delivery.scripted or len(planned.script) < 2:
        raise ValueError("scripted delivery requires at least two messages")
    if planned.script[0] != opening:
        raise ValueError("the scripted opening differs from the generated probe query")
    pairs: list[tuple[str, TargetResponse]] = []
    session: str | None = None
    fatal: BaseException | None = None
    ended = ENDED_BY_BOUND
    for query in planned.script:
        response, fatal = exchange(query, session)
        if response is None:
            ended = ENDED_BY_BUDGET
            break
        pairs.append((query, response))
        session = response.session_id or session or (mint or _mint)()
        if fatal is not None or response.failed:
            ended = ENDED_BY_TARGET_FAILURE
            break
    if not pairs:
        return None, fatal
    return (
        Conversation(
            pairs=tuple(pairs),
            technique=SCRIPTED_TURNS,
            session_id=session,
            ended=ended,
        ),
        fatal,
    )


def _next_turn(
    attacker: AttackerProtocol,
    planned: PlannedDelivery,
    transcript: Sequence[tuple[str, str]],
    *,
    attempts: int,
    backoff: float,
    pause: Callable[[float], None],
) -> tuple[str | None, bool]:
    """What the attacker writes next, and whether it answered at all.

    `(turn, True)` is an answer -- `None` meaning the attacker judged the conversation done.
    `(None, False)` is a provider that failed every attempt, which is the caller's to record as
    such rather than to read as "done".
    """
    assert planned.objective is not None
    for attempt in range(1, max(attempts, 1) + 1):
        try:
            return attacker.next_turn(planned.objective, planned.approach, transcript), True
        except Exception:
            if attempt == max(attempts, 1):
                return None, False
            pause(backoff * (2 ** (attempt - 1)))
    return None, False


def _mint() -> str:
    return secrets.token_hex(8)
