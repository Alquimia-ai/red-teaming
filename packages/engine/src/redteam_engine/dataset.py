"""Assemble replica sessions from explicitly identified graded outcomes."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass

from gaussia.generators.roastme.dataset import report_to_dataset, to_dataset
from gaussia.schemas.common import Dataset
from gaussia.schemas.roastme import FailureReport, GradedOutcome, Probe, RoastBatch

from redteam_engine.outcomes import UnitOutcome

EXPLOIT_SESSION = "exploit"
"""The suffix the search's session gets: `{run_id}:exploit`. The one place that names it; the resume
path reads the session back by the same name."""


class RoastDataset(Dataset):  # type: ignore[misc]  # gaussia ships no stubs
    """A session whose interactions are `RoastBatch`es -- gaussia's dataset with the record kept.

    Narrowing `conversation` is the whole point: without it, re-validating a session from JSON
    validates each interaction as a plain `Batch` and drops the `roast` record, which is the
    control grade and the provenance the turn exists to carry.
    """

    conversation: list[RoastBatch]


@dataclass(frozen=True)
class RoastSessions:
    """The attack dataset: one session per replica, and the search's when it ran."""

    sessions: list[RoastDataset]


def roast_dataset(
    outcomes: Sequence[UnitOutcome],
    report: FailureReport | None,
    *,
    run_id: str,
    assistant_id: str,
    context: str,
    language: str,
) -> RoastSessions:
    by_replica: dict[int, list[tuple[Probe, GradedOutcome]]] = defaultdict(list)
    seen: set[tuple[str, int]] = set()
    for item in outcomes:
        key = item.unit.attack_id, item.unit.replica_idx
        if (
            key in seen
            or item.unit.probe_id != item.probe.id
            or item.outcome.probe_id != item.probe.id
        ):
            raise ValueError("duplicate or inconsistent work-unit outcome")
        seen.add(key)
        by_replica[item.unit.replica_idx].append((item.probe, item.outcome))

    sessions: list[RoastDataset] = []
    for replica in sorted(by_replica):
        base = to_dataset(
            [p for p, _ in by_replica[replica]],
            [o for _, o in by_replica[replica]],
            session_id=f"{run_id}:r{replica}",
            assistant_id=assistant_id,
            context=context,
            language=language,
        )
        sessions.append(as_roast(base))

    if report is not None and report.queries_over_threshold:
        search = report_to_dataset(
            report,
            session_id=f"{run_id}:{EXPLOIT_SESSION}",
            assistant_id=assistant_id,
            context=context,
            language=language,
        )
        sessions.append(as_roast(search))

    return RoastSessions(sessions=sessions)


def as_roast(base: Dataset) -> RoastDataset:
    """gaussia's `Dataset` as a `RoastDataset`, every turn keeping gaussia's record and gaussia's
    `qa_id`.

    gaussia builds the turns as `RoastBatch` and the session as `Dataset`, so the instances already
    carry the record; what changes is the declared type, so the record is not lost on the way back
    from JSON. A turn that is not a `RoastBatch` is refused rather than widened: a session with a
    turn nobody graded is not the attack dataset.
    """
    turns: list[RoastBatch] = []
    for turn in base.conversation:
        if not isinstance(turn, RoastBatch):
            raise TypeError(
                f"turn {turn.qa_id!r} carries no roast record; the attack dataset is built from "
                f"graded exchanges only"
            )
        turns.append(turn)
    return RoastDataset(
        session_id=base.session_id,
        assistant_id=base.assistant_id,
        language=base.language,
        context=base.context,
        chatbot_role=base.chatbot_role,
        conversation=turns,
    )
