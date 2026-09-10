"""Resuming a run: closed units are answered from the store, pending ones by the assistant.

The plan's argument -- "the key exists" and "the unit completed" are the same statement -- says
which units must not be executed again. It does not say what to do with them, and the naive answer
is "nothing": the Profiler sees only the pending tail, so a resumed run profiles the tail, builds a
dataset of the tail, under a manifest whose denominator counts the whole run. The traces hold the
exchange but not the grade, because grading is gaussia's and happens inside `Profiler.profile`,
which hands its outcomes back only at the end.

So the whole plan is profiled on every attempt, and a closed unit is **replayed**: the answer the
assistant already gave is returned to the Profiler as if it had just been given. gaussia is built
for exactly this -- "replaying recorded responses is the same code as a live run rather than a
separate mode" -- and the cost is honest: one judge call per replayed exchange and principle, and
zero conversations with the assistant. The alternative, persisting each grade as it is produced,
would reach into gaussia's private exchange and would still not cover a process that died inside
`profile()`.
"""

from __future__ import annotations

import contextlib
import json
from collections.abc import Iterable, Sequence
from typing import TYPE_CHECKING

from gaussia.core.target_assistant import TargetAssistant
from gaussia.schemas.roastme import TargetResponse

from redteam_contracts.trace import Trace
from redteam_engine.dataset import EXPLOIT_SESSION, RoastDataset
from redteam_store import layout
from redteam_store.codec import decode_trace, encode_json
from redteam_store.interface import ObjectAlreadyExists, ObjectNotFound
from redteam_target.failures import raw_failure

if TYPE_CHECKING:
    from redteam_contracts.plan import WorkUnit
    from redteam_store.interface import ObjectStore

Recorded = dict[tuple[str, int], TargetResponse]
"""`(attack_id, replica_idx)` -> the answer the assistant gave, for every closed unit."""

Replayed = dict[tuple[str, int], Trace]
"""`(attack_id, replica_idx)` -> the trace an earlier attempt closed, for every closed unit."""


def recorded_traces(store: ObjectStore, run_id: str, closed: Iterable[WorkUnit]) -> Replayed:
    """Every closed unit's trace, read once. The answer to replay is one thing read off it; how the
    conversation was delivered and how it ended is another, and the manifest wants both."""
    return {
        (unit.attack_id, unit.replica_idx): decode_trace(
            store.get(layout.trace(run_id, unit.attack_id, unit.replica_idx))
        )
        for unit in closed
    }


def responses_of(replayed: Replayed) -> Recorded:
    """The answer the assistant gave, for every replayed trace: the last agent turn, the one gaussia
    graded. A failed exchange comes back failed, so the Profiler grades it exactly as it would have
    the first time -- not at all."""
    recorded: Recorded = {}
    for key, trace in replayed.items():
        answer = trace.agent_turns[-1]
        recorded[key] = TargetResponse(
            content=answer.content,
            failed=answer.failed,
            failure_reason=answer.failure_reason,
            raw=raw_failure(answer.failure),
        )
    return recorded


def recorded_responses(store: ObjectStore, run_id: str, closed: Iterable[WorkUnit]) -> Recorded:
    """The answer the assistant gave for every closed unit, read back off its trace.

    **The last agent turn, not the first.** A conducted conversation holds several, and the one
    gaussia graded is the answer the escalation obtained -- the last. Replaying the first would
    grade a resumed run on the opening the attacker was told not to press on.
    """
    return responses_of(recorded_traces(store, run_id, closed))


def live_units(units: Sequence[WorkUnit], recorded: Recorded) -> list[WorkUnit]:
    """The units `ResumingTarget` will send to the assistant, in the order it will send them.

    Every unit of the plan with no recorded answer -- which is more than the pending ones: a unit
    marked failed-without-remedy has no trace to replay from, so it goes live too. This is the list
    the recorder has to be built over. Built over the pending units alone, the marked unit's answer
    would land under the next unit's key, with the next unit's probe id, and the last pending answer
    would fall beyond the plan.
    """
    return [unit for unit in units if (unit.attack_id, unit.replica_idx) not in recorded]


class ResumingTarget(TargetAssistant):  # type: ignore[misc]  # gaussia ships no stubs
    """The plan's units in order: closed ones answered from the store, the rest by the governed
    target.

    Sits **outside** `GovernedTarget`, on purpose. A replayed exchange is not a conversation with
    the assistant: it must not be charged to the budget, must not wait on the rate gate, and must
    not be recorded again. The recorder behind the governed target maps the k-th live exchange to
    the k-th of `live_units(units, recorded)`, and that holds exactly because those are the units
    that reach it, in plan order.

    Positional, like the recorder and for the same reason: the Profiler sends one query per probe in
    the order it was handed them. Anything sent past the plan's length is the search's, and goes
    live.
    """

    def __init__(
        self, units: Sequence[WorkUnit], recorded: Recorded, live: TargetAssistant
    ) -> None:
        self._units = list(units)
        self._recorded = recorded
        self._live = live
        self._sent = 0
        self.replayed = 0
        """Exchanges answered from the store. Provenance: how much of the profile this attempt paid
        the judge for and not the assistant."""

    def send(self, query: str, session_id: str | None = None) -> TargetResponse:
        if self._sent < len(self._units):
            unit = self._units[self._sent]
            self._sent += 1
            recorded = self._recorded.get((unit.attack_id, unit.replica_idx))
            if recorded is not None:
                self.replayed += 1
                return recorded
        return self._live.send(query, session_id)


def closed_conduction(store: ObjectStore, run_id: str) -> dict[str, str]:
    """What an earlier attempt's conduction reported, for a run whose dataset is already in the
    store."""
    try:
        recorded = {
            str(k): str(v) for k, v in json.loads(store.get(layout.conduction(run_id))).items()
        }
    except ObjectNotFound:
        recorded = {}
    return {**recorded, "conduct": "closed by an earlier attempt: the dataset was in the store"}


def remember_exploit(
    store: ObjectStore, run_id: str, searched: dict[str, str], sessions: list[RoastDataset]
) -> None:
    """The search was attempted: say how it went, and keep its session, before anything else can
    fail.

    Written from inside conduction, the moment the report exists, because the dataset is assembled
    later. An attempt that died between the two would otherwise resume by searching again --
    generated queries against the assistant, twice -- or by losing what the first search found. The
    marker is what `exploiter_for` reads, and it carries what the search reported about itself --
    `ran` with its categories, or `failed` and why -- so a relaunch that skips the search still
    puts the search's provenance in the manifest. A failed search is remembered as much as one that
    ran: it, too, sent queries. The session is what the dataset gets back.
    """
    with contextlib.suppress(ObjectAlreadyExists):
        store.put(
            layout.searched(run_id),
            json.dumps({"components": searched}).encode(),
            content_type="application/json",
        )
    for session in sessions:
        if session.session_id == f"{run_id}:{EXPLOIT_SESSION}":
            with contextlib.suppress(ObjectAlreadyExists):
                store.put(
                    layout.session(run_id, EXPLOIT_SESSION),
                    encode_json(session.model_dump(mode="json")),
                    content_type="application/json",
                )


def remembered_exploit(
    store: ObjectStore, run_id: str
) -> tuple[dict[str, str], list[RoastDataset]]:
    """What an earlier attempt's search reported about itself, and its session if it left one.

    Both empty when no earlier attempt searched. The components outrank this attempt's own
    "skipped: an earlier attempt already exploited": the manifest describes the run, and the run's
    search ran -- or failed -- once.
    """
    try:
        marker = json.loads(store.get(layout.searched(run_id)))
    except ObjectNotFound:
        return {}, []
    components = {str(k): str(v) for k, v in (marker.get("components") or {}).items()}
    try:
        raw = store.get(layout.session(run_id, EXPLOIT_SESSION))
    except ObjectNotFound:
        return components, []
    return components, [RoastDataset.model_validate(json.loads(raw))]
