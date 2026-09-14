"""Read completed traces for replay and recover atomic conduction checkpoints.

Replay reuses the final agent response, including failure metadata. The profiler may regrade it,
but no live target call is made. Dataset and exploit recovery retain their original provenance."""

from __future__ import annotations

import json
from collections.abc import Iterable, Sequence

from gaussia.schemas.roastme import TargetResponse

from redteam_contracts.plan import WorkUnit
from redteam_contracts.trace import Trace
from redteam_engine.checkpoints import Checkpoint, RecoveryIncomplete, put_same, read, save
from redteam_engine.dataset import EXPLOIT_SESSION, RoastDataset
from redteam_store import layout
from redteam_store.codec import decode_trace, encode_json
from redteam_store.interface import ObjectNotFound, ObjectStore
from redteam_target.failures import raw_failure

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
    """Units without completed traces, including those with failure markers."""
    return [unit for unit in units if (unit.attack_id, unit.replica_idx) not in recorded]


def closed_conduction(store: ObjectStore, run_id: str) -> dict[str, str]:
    """Complete partial projections, or refuse a legacy dataset without provenance."""
    key = layout.recovery(run_id, "conduction")
    if store.exists(key):
        record = read(store, key)
        project_conduction(store, run_id, record)
        components = record.components
    else:
        try:
            components = json.loads(store.get(layout.conduction(run_id)))
            if not isinstance(components, dict) or not components:
                raise ValueError("missing provenance")
            for session in json.loads(store.get(layout.dataset(run_id))):
                RoastDataset.model_validate(session)
        except (ObjectNotFound, ValueError) as missing:
            raise RecoveryIncomplete(
                "dataset has no recoverable conduction provenance; start a new run"
            ) from missing
    return {
        **components,
        "conduct": "closed by an earlier attempt: verified dataset and provenance",
    }


def project_conduction(store: ObjectStore, run_id: str, record: Checkpoint) -> None:
    put_same(
        store,
        layout.dataset(run_id),
        encode_json([session.model_dump(mode="json") for session in record.sessions]),
    )
    put_same(store, layout.conduction(run_id), encode_json(record.components))


def remember_conduction(
    store: ObjectStore, run_id: str, components: dict[str, str], sessions: list[RoastDataset]
) -> None:
    record = Checkpoint(components=components, sessions=sessions)
    save(store, layout.recovery(run_id, "conduction"), record)
    project_conduction(store, run_id, record)


def remember_exploit(
    store: ObjectStore, run_id: str, searched: dict[str, str], sessions: list[RoastDataset]
) -> None:
    """The commit includes the sessions, even when the valid answer is an empty list."""
    record = Checkpoint(
        components=searched,
        sessions=[
            session for session in sessions if session.session_id == f"{run_id}:{EXPLOIT_SESSION}"
        ],
    )
    save(store, layout.recovery(run_id, "exploit"), record)
    _project_exploit(store, run_id, record)


def _project_exploit(store: ObjectStore, run_id: str, record: Checkpoint) -> None:
    for session in record.sessions:
        put_same(
            store,
            layout.session(run_id, EXPLOIT_SESSION),
            encode_json(session.model_dump(mode="json")),
        )
    put_same(store, layout.searched(run_id), encode_json({"components": record.components}))


def remembered_exploit(
    store: ObjectStore, run_id: str
) -> tuple[dict[str, str], list[RoastDataset]]:
    key = layout.recovery(run_id, "exploit")
    if store.exists(key):
        record = read(store, key)
        _project_exploit(store, run_id, record)
        return record.components, record.sessions
    try:
        marker = json.loads(store.get(layout.searched(run_id)))
    except ObjectNotFound:
        if store.exists(layout.recovery(run_id, "exploit-started")) or store.exists(
            layout.exploit(run_id)
        ):
            raise RecoveryIncomplete(
                "search started without a recoverable checkpoint; start a new run"
            ) from None
        return {}, []
    components = {str(k): str(v) for k, v in (marker.get("components") or {}).items()}
    try:
        raw = store.get(layout.session(run_id, EXPLOIT_SESSION))
    except ObjectNotFound as missing:
        raise RecoveryIncomplete(
            "legacy search has no recoverable session; start a new run"
        ) from missing
    if not components:
        raise RecoveryIncomplete("legacy search has no provenance; start a new run")
    return components, [RoastDataset.model_validate_json(raw)]
