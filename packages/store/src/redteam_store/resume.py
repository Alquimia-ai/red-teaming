"""Resumption, progress and coverage are the same difference over the same keys.

The argument, worth being able to reconstruct because it is why the platform has no database:

1. Traces have to be written anyway -- they are the evidence and they are the contract.
2. If the unit of work is one replica of one attack, each closed unit produces exactly one trace.
3. If that trace's key derives from the plan, it is known before executing.
4. Then "the key exists" and "the unit completed" are the same statement.
5. So the progress record does not need writing separately: it is already written.

What that buys is not one less piece to operate. It is that progress **cannot disagree** with the
result, because both are derived from the same keys. A counter in a table can go stale,
double-count, or be lost in a crash. A listing of objects cannot.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from redteam_contracts.manifest import Coverage, CoverageReport
from redteam_contracts.plan import Plan, WorkUnit
from redteam_store import layout
from redteam_store.interface import ObjectStore


@dataclass(frozen=True)
class RunDifference:
    """What the plan wanted, against what the store holds."""

    pending: tuple[WorkUnit, ...]
    """Never ran, or ran and did not close. These are what a resumed runner executes."""

    closed: tuple[WorkUnit, ...]
    """Closed and immutable. Never re-executed -- that is the point of the whole scheme."""

    failed: tuple[WorkUnit, ...]
    """Failed without remedy, marked as such.

    Distinguishing these from `pending` is why the failure marker exists: listing says what is
    there, not why what is missing is missing. How many times to retry before writing a marker is
    policy, and the policy belongs to whoever owns the job.
    """

    @property
    def is_complete(self) -> bool:
        """A run is finished when the difference is empty. Not a statistical criterion -- a property
        of the store."""
        return not self.pending

    def coverage(self) -> CoverageReport:
        """The same difference, counted the way a reader asks about it: in total, per plugin and
        per strategy. Controls have no plugin and count only in the total and their strategy."""
        planned: Counter[str] = Counter()
        closed: Counter[str] = Counter()
        failed: Counter[str] = Counter()
        for units, counter in (
            (self.pending + self.closed + self.failed, planned),
            (self.closed, closed),
            (self.failed, failed),
        ):
            for unit in units:
                counter["*"] += 1
                if unit.plugin is not None:
                    counter[f"plugin:{unit.plugin}"] += 1
                if unit.strategy is not None:
                    counter[f"strategy:{unit.strategy}"] += 1

        def slice_(key: str) -> Coverage:
            return Coverage(planned=planned[key], closed=closed[key], failed=failed[key])

        return CoverageReport(
            total=slice_("*"),
            by_plugin={
                key.removeprefix("plugin:"): slice_(key)
                for key in sorted(planned)
                if key.startswith("plugin:")
            },
            by_strategy={
                key.removeprefix("strategy:"): slice_(key)
                for key in sorted(planned)
                if key.startswith("strategy:")
            },
        )


def difference(store: ObjectStore, plan: Plan) -> RunDifference:
    """Diff the plan against the store. One listing, no other question to ask.

    Lists the trace prefix once rather than probing each key: a run has thousands of units, and one
    listing beats thousands of round trips.
    """
    present = set(store.list_prefix(layout.traces_prefix(plan.run_id) + "/"))

    pending: list[WorkUnit] = []
    closed: list[WorkUnit] = []
    failed: list[WorkUnit] = []

    for unit in plan.units:
        trace_key = layout.trace(plan.run_id, unit.attack_id, unit.replica_idx)
        failure_key = layout.trace_failure(plan.run_id, unit.attack_id, unit.replica_idx)
        if trace_key in present:
            closed.append(unit)
        elif failure_key in present:
            failed.append(unit)
        else:
            pending.append(unit)

    return RunDifference(pending=tuple(pending), closed=tuple(closed), failed=tuple(failed))
