"""Run state, derived rather than stored.

There is no table of runs with a status column somebody has to remember to update. The API lists the
store and answers with what is actually there; then it asks the platform whether the process that
should be writing there is still alive.

Planned units come from the frozen spec and the pinned probe set; closed and failed ones from
counting the keys under the run's prefix. Both numbers come from the same source that will produce
the final result, **so they cannot disagree with it**. Liveness is the one thing the store cannot
answer, and the platform is the only account of it: a run whose store says the attack is under way
and whose platform says no such process exists is **stalled**, and the remedy is a relaunch that
resumes from the difference.
"""

from __future__ import annotations

from dataclasses import dataclass

from redteam_contracts.manifest import RunPhase
from redteam_dispatch import JobState
from redteam_store import layout
from redteam_store.interface import ObjectStore

UNDER_WAY = frozenset({RunPhase.GENERATING, RunPhase.ATTACKING})
"""The phases during which a runner has to be alive for the run to be moving."""

GONE = frozenset({JobState.UNKNOWN, JobState.FAILED})
"""The platform's answers that mean no process is going to write the next key."""


@dataclass(frozen=True)
class RunStatus:
    run_id: str
    phase: RunPhase
    """What the store says: derived from which artifacts exist, in the order they are written."""

    runner: JobState
    """What the platform says about the run's process, right now."""

    planned: int | None
    """None until generation closes: the probe count does not exist before then."""

    closed: int
    failed: int

    @property
    def pending(self) -> int | None:
        if self.planned is None:
            return None
        return max(self.planned - self.closed - self.failed, 0)

    @property
    def stalled(self) -> bool:
        """The store says the run is under way and the platform says nothing is running it.

        Not a phase of its own: the store's account is still true -- those traces closed -- and a
        relaunch picks the run up exactly where it is. It is the disagreement that is reported,
        because it is the one thing neither source can say alone.
        """
        return self.phase in UNDER_WAY and self.runner in GONE


def derive(store: ObjectStore, run_id: str, planned: int | None, runner: JobState) -> RunStatus:
    """Read the phase and the progress off the store, and set the platform's answer beside them.

    Raises:
        KeyError: No spec under this id; the API never accepted the run.
    """
    if not store.exists(layout.spec(run_id)):
        raise KeyError(run_id)

    keys = store.list_prefix(layout.run_prefix(run_id) + "/")
    closed = sum(1 for k in keys if k.endswith(".jsonl.zst"))
    failed = sum(1 for k in keys if k.endswith(".failed"))

    return RunStatus(
        run_id=run_id,
        phase=_phase(keys),
        runner=runner,
        planned=planned,
        closed=closed,
        failed=failed,
    )


def _phase(keys: list[str]) -> RunPhase:
    """Which artifacts exist, read in the order they are written. Each is created at the moment the
    thing it names stops being able to change, so their presence is the phase."""
    if any(k.endswith("/manifest.json") for k in keys):
        # COMPLETE by construction: a failed attempt writes under its own key, never here.
        return RunPhase.COMPLETE
    if _newest_attempt_died(keys):
        # Not a lost run: everything that closed is in the store, a relaunched runner resumes from
        # the difference, and this reads `complete` once it closes. Until a relaunch begins,
        # `failed` is the honest answer, and the one a consumer's poll loop waits for.
        return RunPhase.FAILED
    if any(k.endswith("/probes.json") or "/traces/" in k for k in keys):
        # The probe set is pinned, so generation closed and the attack is what follows -- whether or
        # not a trace has landed yet.
        return RunPhase.ATTACKING
    if any(layout.parse_attempt_key(k) is not None for k in keys):
        # An attempt announced itself and has not pinned a probe set: it is generating.
        return RunPhase.GENERATING
    return RunPhase.ACCEPTED


def _newest_attempt_died(keys: list[str]) -> bool:
    """Whether the attempt that most recently began is one that left a failure record.

    A record on its own would hold the status at `failed` for the whole life of the relaunch:
    attempt two attacking while this still read attempt one's death, and a consumer's poll loop,
    which stops on `failed`, giving up exactly when the retry policy resumed. Every attempt
    announces itself before it does anything, so the newest one is a listing away, and only its
    record counts.
    """
    failures = {parsed[1] for k in keys if (parsed := layout.parse_failure_key(k)) is not None}
    if not failures:
        return False
    attempts = sorted(
        parsed[1] for k in keys if (parsed := layout.parse_attempt_key(k)) is not None
    )
    return not attempts or attempts[-1] in failures
