"""A graded result retains the work unit that produced it."""

from dataclasses import dataclass

from gaussia.schemas.roastme import GradedOutcome, Probe

from redteam_contracts.plan import WorkUnit


@dataclass(frozen=True)
class UnitOutcome:
    unit: WorkUnit
    probe: Probe
    outcome: GradedOutcome
