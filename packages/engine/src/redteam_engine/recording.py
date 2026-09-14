"""Persist conversations under explicit planned identities or exploitation keys."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from gaussia.schemas.roastme import TargetResponse

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
    def __init__(
        self,
        store: ObjectStore,
        run_id: str,
        probes: Mapping[str, Mapping[str, Any]],
    ) -> None:
        self._store = store
        self._run_id = run_id
        self._probes = probes
        self.written = 0
        """Traces written: exchanges the assistant answered, planned or beyond the plan."""

        self.beyond_plan = 0
        """Exchanges recorded that no unit planned -- the search's own conversations."""

        self.failed = 0
        """Planned units marked failed this attempt: sent, not answered, left for the next one."""

    def __call__(
        self, query: str, response: TargetResponse, conversation: Conversation | None = None
    ) -> None:
        """Record an exploitation exchange, which has no planned identity."""
        self._record_beyond_plan(
            conversation if conversation is not None else static(query, response)
        )

    def record(
        self,
        unit: WorkUnit,
        query: str,
        response: TargetResponse,
        conversation: Conversation | None = None,
    ) -> None:
        conversation = conversation if conversation is not None else static(query, response)
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
            json.dumps({"phase": EXPLOIT, "query": conversation.opening}, sort_keys=True).encode()
        ).hexdigest()[:_IDENTITY_CHARS]
        self.beyond_plan += 1
        self._write(
            attack_id=attack_id,
            replica_idx=0,
            probe_id=f"{EXPLOIT}-generated",
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

    def _mark_failed(self, unit: WorkUnit, response: TargetResponse) -> None:
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
