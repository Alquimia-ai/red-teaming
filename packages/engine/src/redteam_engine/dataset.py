"""Building the attack dataset from what conduction produced.

The deliverable, assembled with gaussia's own `to_dataset` (the Profiler's half) and
`report_to_dataset` (the Exploiter's), then widened with the one thing gaussia does not carry: the
per-replica split. Nothing of gaussia's records is re-implemented -- every turn keeps gaussia's
`RoastBatch`, with the record on it.

**One session per replica.** `to_dataset` keys outcomes by `probe_id`, so N replicas of one probe in
one call collapse to the last. The Profiler is handed every unit of the plan in order -- the same
probe once per replica, closed ones replayed from their traces -- so grouping by replica index and
building a session each keeps every replica, and a reader aggregates per session, which is what
returns replica-level results raw.

**Outcomes are matched to units by position, never by `probe_id`.** Every replica of a probe shares
the id, so keying on it collapses N graded outcomes into the last one: N identical sessions, and a
replica variance of zero by construction. gaussia's `Profiler.profile` is one `send` per probe, in
the order it was handed them, with no retry, skip or reorder -- so `outcomes[i]` grades `probes[i]`,
and that is the same contract the recorder maps traces by.

**The session type narrows `conversation`.** gaussia's `Dataset` declares `list[Batch]`, so a
session read back from JSON would validate each turn as a plain `Batch` and drop the record.
`RoastDataset` declares `list[RoastBatch]`, and the record survives the round trip through the
store.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from gaussia.generators.roastme.dataset import report_to_dataset, to_dataset
from gaussia.schemas.common import Dataset
from gaussia.schemas.roastme import RoastBatch

if TYPE_CHECKING:
    from gaussia.schemas.roastme import FailureReport, GradedOutcome, Probe, ProfilerResult

    from redteam_contracts.plan import WorkUnit

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
    units: list[WorkUnit],
    probes: list[Probe],
    result: ProfilerResult,
    report: FailureReport | None,
    *,
    run_id: str,
    assistant_id: str,
    context: str,
    language: str,
) -> RoastSessions:
    """The attack dataset: one session per replica, plus the search's session when there was one.

    Args:
        units: Every unit of the plan, in the order the Profiler was handed them -- closed ones
            replayed, pending ones live. `probes[i]`, `outcomes[i]` and `units[i]` are the same
            exchange; that is how the recorder mapped them, and it is how the replica of each turn
            is known.
        probes: One per unit, in that order.
        result: The Profiler's output; `result.outcomes[i]` grades `probes[i]`.
        report: The Exploiter's, or None when the search did not run.
        assistant_id: The assistant the run attacked, as the connector names it.
        context: One phrase for what the assistant is; the run's declared domain.
        language: The language the probes are written in, as the run declared it.
    """
    by_replica: dict[int, list[tuple[Probe, GradedOutcome]]] = defaultdict(list)
    for unit, probe, outcome in zip(units, probes, result.outcomes, strict=True):
        by_replica[unit.replica_idx].append((probe, outcome))

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


def as_roast(base: Any) -> RoastDataset:
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
