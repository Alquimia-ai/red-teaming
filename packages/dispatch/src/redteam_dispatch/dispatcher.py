"""What every dispatch backend promises: launch one runner per run, and say whether it is alive."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol, runtime_checkable

from redteam_contracts.run_id import check


class DispatchError(RuntimeError):
    pass


class AlreadyRunning(DispatchError):
    """The platform refused because a job for this run already exists.

    Not a problem to route around: it is the uniqueness invariant working. The right response is to
    let the existing run continue.
    """


@dataclass(frozen=True)
class JobHandle:
    run_id: str
    backend: str
    identifier: str
    """What the platform calls it: a container id, a Job uid, a pid."""


class JobState(StrEnum):
    """What the platform says about a run's process. Liveness, and nothing about progress: progress
    is the store's to answer, by counting keys."""

    UNKNOWN = "unknown"
    """The platform has no record of a job for this run: never launched here, already removed, or
    a platform this process cannot ask. The API reads a run whose store says the attack is under
    way and whose platform says this as stalled."""

    PENDING = "pending"
    """Created and not yet running: an image being pulled, a pod being scheduled."""

    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"

    @property
    def alive(self) -> bool:
        return self in (JobState.PENDING, JobState.RUNNING)


@runtime_checkable
class Dispatcher(Protocol):
    def launch(
        self,
        run_id: str,
        *,
        env: Mapping[str, str] | None = None,
        secret_refs: Sequence[str] = (),
    ) -> JobHandle:
        """Start one runner for `run_id`.

        `env` is what this run's process needs and nothing else has to be kept secret: the store
        wiring, typically. `secret_refs` names the credentials the run declared -- the target's,
        the judge's -- and how each reaches the process is the backend's business: a subprocess or
        a container is handed the resolved value in its environment, a Job is handed a reference
        into the platform's secret and never the value. Passed per launch rather than configured
        on the dispatcher, so a runner receives exactly the secrets its own spec named and nothing
        another run's did.
        """
        ...

    def status(self, run_id: str) -> JobState:
        """What the platform says about this run's process, right now."""
        ...


JOB_PREFIX = "redteam-run-"
"""What a run's job is called, before the run id.

A job name has to fit a DNS-1123 label -- 63 characters -- which is why `redteam_contracts.run_id`
caps an id at 50: this prefix is 12, and 12 + 50 stays under 63. One prefix, because one run has one
job.
"""

ENTRYPOINT = ("redteam-runner",)
"""What runs a run: the runner's console script, on the image's `PATH` and in the development
environment alike. The container image declares it as its `ENTRYPOINT`, so a container is handed
only the arguments; a subprocess is handed the whole command."""


def job_name(run_id: str) -> str:
    """The run's job, so a duplicate launch collides instead of duplicating work.

    The id verbatim behind the prefix, and a refusal for an id outside the rule -- never a
    normalisation, because two ids that normalise to one name are two runs the platform cannot tell
    apart.
    """
    return f"{JOB_PREFIX}{check(run_id)}"
