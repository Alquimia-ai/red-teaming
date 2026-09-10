"""Writing each conversation the instant it closes, under the key the plan gave it.

The plan's whole argument rests on one property: the key of a work unit is derivable before it is
executed, so "the key exists" and "the unit completed" are the same statement. This is the object
that keeps the promise on the profiling side. It sits behind `GovernedTarget.on_exchange`, so every
exchange the Profiler makes is written before the next one is sent -- a runner that dies between two
probes has lost nothing it paid for.

**The mapping from exchange to unit is positional, on purpose.** gaussia's Profiler sends its probes
one by one, in the order it was handed them, and calls the target once per probe. So the k-th
exchange the target sees belongs to the k-th probe the Profiler was given -- and the target in front
of this recorder lets through exactly the units with no recorded answer, in plan order. Mapping by
query text instead would break the day two strategies phrase the same question, which a catalogue
is free to do.

Exchanges the search generates have no unit behind them: they are evidence beyond the plan, keyed
by their own content and aimed at no plugin. They count as evidence, never as coverage -- which is
exactly the distinction the coverage report exists to draw.

**A failed exchange does not close its unit.** Written under the planned key like any answer, "the
key exists" would say "the unit completed" about a unit the assistant never answered: the resumed
run would replay the failure into the judge, the thin-profile ratio would count it again, and the
only way to ever retry that probe would be a new run id. A transport failure is written under the
unit's failure marker instead, with the record as its body, so the difference reports the unit
`failed`, the next attempt sends it live, and the evidence of what went wrong is still in the store.

**An exchange is a conversation, and a trace is all of it.** The door hands over every turn it
sent and every answer it read -- one pair for a static delivery, several for a conducted one -- and
the trace carries them all, in order, under the one key the unit has. The labels say what it
charged, how it was delivered, how deep it went, who steered it and why it stopped; the same trace
read by the next attempt replays its last answer, which is the one gaussia graded.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Any

from redteam_contracts.trace import Role, Trace, TraceLabels, Turn
from redteam_engine.planned import Conversation, static
from redteam_store import layout
from redteam_store.codec import encode_trace
from redteam_store.interface import ObjectAlreadyExists
from redteam_target.failures import failure_of

if TYPE_CHECKING:
    from redteam_contracts.plan import WorkUnit
    from redteam_store.interface import ObjectStore

PROFILE = "profile"
EXPLOIT = "exploit"
"""The two phases of conduction. They decide which key an exchange is written under -- the plan's,
or one derived from the query -- and nothing else about the trace: how it was delivered is the
conversation's to say."""

_IDENTITY_CHARS = 32


class Recorder:
    """Turns `(query, response)` into a written trace, keyed by phase.

    Args:
        store: Where traces go. Append-only, which is what makes a second attempt at a closed unit
            harmless rather than a duplicate.
        run_id: The run every trace belongs to.
        live: The units that will reach the target live, **in the order they will reach it** --
            every unit of the plan with no recorded answer. The k-th exchange is the k-th of these.
        probes: The probe each unit sends, by probe id, so the trace can carry what it aimed at.
    """

    def __init__(
        self,
        store: ObjectStore,
        run_id: str,
        live: Sequence[WorkUnit],
        probes: Mapping[str, Mapping[str, Any]],
    ) -> None:
        self._store = store
        self._run_id = run_id
        self._live = list(live)
        self._probes = probes
        self._sent = 0
        self.phase = PROFILE
        self.written = 0
        """Traces written: exchanges the assistant answered, planned or beyond the plan."""

        self.beyond_plan = 0
        """Exchanges recorded that no unit planned -- the search's own conversations."""

        self.failed = 0
        """Planned units marked failed this attempt: sent, not answered, left for the next one."""

    def __call__(self, query: str, response: Any, conversation: Conversation | None = None) -> None:
        """One closed exchange. `query` and `response` are its opening and its final answer;
        `conversation` is all of it, and `None` means the one pair those two make."""
        whole = conversation if conversation is not None else static(query, response)
        if self.phase == PROFILE:
            self._record_planned(whole)
        else:
            self._record_beyond_plan(whole)

    def _record_planned(self, conversation: Conversation) -> None:
        if self._sent >= len(self._live):
            # The Profiler sent more than it was given, which the library does not do. Recording it
            # as beyond the plan keeps the evidence and keeps the denominator honest.
            self._record_beyond_plan(conversation)
            return
        unit = self._live[self._sent]
        self._sent += 1
        if conversation.final.failed:
            # The cursor advanced -- the Profiler counted this probe -- but nothing closes: the unit
            # is marked, not written, and the record of what went wrong is the marker's body. A
            # conducted conversation whose last turn failed is in the same position: the turns
            # before it were answered, but the unit was not, and the next attempt conducts it again.
            self._mark_failed(unit, conversation.final)
            return
        probe = self._probes.get(unit.probe_id, {})
        hook = probe.get("hook") or {}
        self._write(
            attack_id=unit.attack_id,
            replica_idx=unit.replica_idx,
            probe_id=unit.probe_id,
            conversation=conversation,
            labels=self._labels(
                conversation,
                plugin=unit.plugin,
                strategy=unit.strategy,
                principle=_text(hook.get("principle")),
                attacked_entity=_text(hook.get("references")),
            ),
        )

    def _record_beyond_plan(self, conversation: Conversation) -> None:
        attack_id = hashlib.sha256(
            json.dumps(
                {"phase": self.phase, "query": conversation.opening}, sort_keys=True
            ).encode()
        ).hexdigest()[:_IDENTITY_CHARS]
        self.beyond_plan += 1
        self._write(
            attack_id=attack_id,
            replica_idx=0,
            probe_id=f"{self.phase}-generated",
            conversation=conversation,
            labels=self._labels(conversation),
        )

    @staticmethod
    def _labels(
        conversation: Conversation,
        *,
        plugin: str | None = None,
        strategy: str | None = None,
        principle: str | None = None,
        attacked_entity: str | None = None,
    ) -> TraceLabels:
        """What the attack charged, and how it was conducted -- the latter read off the conversation
        rather than assumed."""
        return TraceLabels(
            plugin=plugin,
            strategy=strategy,
            principle=principle,
            turn_depth=conversation.depth,
            attacked_entity=attacked_entity,
            orchestration_technique=conversation.technique,
            attacker=conversation.attacker,
            session_id=conversation.session_id,
            ended=conversation.ended,
        )

    def _mark_failed(self, unit: WorkUnit, response: Any) -> None:
        """The unit's failure marker, carrying the record. Idempotent across attempts: an earlier
        attempt's marker says the same thing, and the store is the record."""
        failure = failure_of(response)
        body = failure.model_dump_json().encode() if failure is not None else b""
        try:
            self._store.put(
                layout.trace_failure(self._run_id, unit.attack_id, unit.replica_idx),
                body,
                content_type="application/json",
            )
        except ObjectAlreadyExists:
            return
        self.failed += 1

    def _write(
        self,
        *,
        attack_id: str,
        replica_idx: int,
        probe_id: str,
        conversation: Conversation,
        labels: TraceLabels,
    ) -> None:
        turns: list[Turn] = []
        for query, response in conversation.pairs:
            turns.append(Turn(idx=len(turns), role=Role.ATTACKER, content=query))
            turns.append(
                Turn(
                    idx=len(turns),
                    role=Role.AGENT,
                    content=response.content,
                    failed=response.failed,
                    failure_reason=response.failure_reason,
                    failure=failure_of(response),
                )
            )
        trace = Trace(
            trace_id=f"{attack_id}-{replica_idx}",
            run_id=self._run_id,
            attack_id=attack_id,
            replica_idx=replica_idx,
            probe_id=probe_id,
            turns=tuple(turns),
            labels=labels,
        )
        try:
            self._store.put(layout.trace(self._run_id, attack_id, replica_idx), encode_trace(trace))
        except ObjectAlreadyExists:
            # Another attempt closed it first. Not an error: the store is the record, and the
            # record already says this unit is done.
            return
        self.written += 1


def _text(value: Any) -> str | None:
    return str(value) if value else None
