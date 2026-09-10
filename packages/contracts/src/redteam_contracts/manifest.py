"""The manifest: the one file a consumer reads to know whether a run is usable.

It ties the run's artifacts together -- the traces, the attack dataset, the weakness profile, the
exploitation report -- with the coverage that says what was planned, what closed and what failed,
and the provenance a reader needs to decide "can I use this, and what can I compare it to".

Two of the artifacts it names are **control artifacts**. The profile and the exploitation report
record how the run steered itself: which principles the control judge saw broken most, which
categories of interaction the search found to break the assistant reproducibly. They are the
run's own instruments reporting on the run, and they are delivered because an operator wants to
read them -- but their scores never enter the coverage, and the coverage never depends on them.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from redteam_contracts.failure import TransportFailure


class RunPhase(StrEnum):
    ACCEPTED = "accepted"
    GENERATING = "generating"
    ATTACKING = "attacking"
    COMPLETE = "complete"
    FAILED = "failed"
    """Not a lost run. Everything that closed is in the store, and the consumer decides whether the
    partial thing is useful."""


class Coverage(BaseModel):
    """Planned against what happened, for one slice of the plan.

    Three numbers and nothing derived from them: a rate is the reader's to compute, over a
    denominator the reader can see.
    """

    model_config = ConfigDict(frozen=True)

    planned: int = Field(ge=0)
    """Units the plan aimed at this slice. The denominator."""

    closed: int = Field(ge=0)
    """Units whose conversation closed and was written as a trace."""

    failed: int = Field(ge=0)
    """Units that failed without remedy and were marked as such."""

    @property
    def pending(self) -> int:
        """Never ran, or ran and did not close. Zero on a run that finished."""
        return self.planned - self.closed - self.failed


class CoverageReport(BaseModel):
    """The difference between the plan and the store, sliced the way a reader asks about it.

    `total` is the whole plan; the slices are per risk family and per strategy, so "was this
    family tested, and how much of it closed" is a lookup rather than a computation over traces.
    Every number here is derived from the same keys resumption reads, which is why it cannot
    disagree with what the store holds.
    """

    model_config = ConfigDict(frozen=True)

    total: Coverage
    by_plugin: dict[str, Coverage] = Field(default_factory=dict)
    by_strategy: dict[str, Coverage] = Field(default_factory=dict)


class FailureRecord(BaseModel):
    """One attempt that ended in an error. Written under its own key, never as the manifest.

    The manifest means the run closed; this means one process died after the attack began, and says
    why. The traces it wrote are in the store, and the next attempt resumes from the difference. A
    consumer polling the status reads `failed` while this is the latest thing written, and
    `complete` once a later attempt closes the run.
    """

    model_config = ConfigDict(frozen=True)

    run_id: str
    attempt: str
    """Identifies the attempt, and is the record's key. Attempts are ordered by it."""

    error: str
    """The exception's type and message, truncated. What to fix before relaunching, if anything."""

    n_traces: int = Field(ge=0)
    """How many conversations were closed when this attempt died -- all of them still in the
    store."""

    resumed: int = Field(ge=0)
    """How many of those were closed before this attempt started."""

    dataset: str | None = None
    """The attack dataset's key, when this attempt got as far as writing one."""

    kind: str | None = None
    """The kind of transport failure this attempt died of, when the channel to the target is what
    failed -- `unauthorized`, `rate_limited` -- so a reader knows what to fix before relaunching
    without opening a trace. None when the attempt died of something else."""

    failure: TransportFailure | None = None
    """The representative record behind `kind`: status, what the target said, what it asked for."""


class Manifest(BaseModel):
    """The run closed. Its phase is always COMPLETE: a failed attempt writes a `FailureRecord`."""

    model_config = ConfigDict(frozen=True)

    run_id: str
    phase: RunPhase
    spec_digest: str
    probes_digest: str | None = None

    dataset: str | None = None
    """The attack dataset's key: one session per replica, built from the traces and the control
    grades. `None` only for a run that closed before conduction produced one."""

    profile: str | None = None
    """The weakness profile's key. A control artifact: how the run read the assistant in order to
    decide what to press on."""

    exploit: str | None = None
    """The exploitation report's key. A control artifact: the categories the search ranked and the
    queries that crossed its threshold. `None` when the run did not exploit, and `components`
    says why."""

    n_total_traces: int = Field(ge=0)
    """Mandatory. The evidence the dataset was built from."""

    coverage: CoverageReport
    """Planned, closed and failed, in total and per plugin and strategy. Derived from the store."""

    components: dict[str, str] = Field(default_factory=dict)
    """Which implementation of each substitutable piece ran -- the target, the control judge, the
    generator, the attackers, the search's collaborators -- and, for a stage that did not run, why.
    Provenance for the parts that can be swapped."""
