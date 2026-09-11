"""Launching one runner per run, and asking the platform whether it is still there.

Three backends, one caller. All three honour the same invariant: **one run is one process.** The
job's name is derived from the `run_id` and nothing else, so a duplicate launch collides in the
platform rather than producing two runners -- and two runners on one run means attacking the same
assistant twice, with doubled cost, doubled load on somebody else's infrastructure, and a result
whose denominator is inflated with duplicate traces. The platform is the first line; the store's
conditional writes are the second, catching a duplicate runner at its first trace rather than never.

The platform is also the only account of whether a runner is alive. The store says what closed; it
cannot say whether the process that was closing things is still running, and a second record that
tried to would drift from the first. So `status` asks the platform -- the Job, the container, the
process -- and the API reads a run whose store says "attacking" and whose platform says "gone" as
stalled.
"""

from redteam_dispatch.backends import (
    AVAILABLE,
    DispatchBackendUnavailable,
    build_dispatcher,
)
from redteam_dispatch.dispatcher import (
    ENTRYPOINT,
    JOB_PREFIX,
    AlreadyRunning,
    Dispatcher,
    DispatchError,
    JobHandle,
    JobState,
    job_name,
)

__all__ = [
    "AVAILABLE",
    "ENTRYPOINT",
    "JOB_PREFIX",
    "AlreadyRunning",
    "DispatchBackendUnavailable",
    "DispatchError",
    "Dispatcher",
    "JobHandle",
    "JobState",
    "build_dispatcher",
    "job_name",
]
