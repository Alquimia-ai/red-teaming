"""A runner as a subprocess on this host. The development loop's backend.

A convenience, not a deployment topology: nothing here enforces uniqueness across machines, and a
process this dispatcher did not start is one it knows nothing about. What it does enforce is the
same shape the other backends have -- one launch per run, refused while the last one is alive, and a
liveness answer read off the process rather than remembered.
"""

from __future__ import annotations

import os
import subprocess
from collections.abc import Mapping, Sequence

from redteam_dispatch.dispatcher import (
    ENTRYPOINT,
    AlreadyRunning,
    JobHandle,
    JobState,
    job_name,
)
from redteam_secrets.resolver import SecretResolver

BACKEND = "local_subprocess"


class LocalSubprocessDispatcher:
    def __init__(
        self,
        resolver: SecretResolver,
        *,
        command: Sequence[str] = ENTRYPOINT,
        env: Mapping[str, str] | None = None,
    ) -> None:
        self._resolver = resolver
        self._command = tuple(command)
        self._env = dict(env or {})
        self._running: dict[str, subprocess.Popen[bytes]] = {}

    def launch(
        self,
        run_id: str,
        *,
        env: Mapping[str, str] | None = None,
        secret_refs: Sequence[str] = (),
    ) -> JobHandle:
        name = job_name(run_id)
        existing = self._running.get(run_id)
        if existing is not None and existing.poll() is None:
            raise AlreadyRunning(f"{name} is already running in this process (pid {existing.pid})")
        # The subprocess inherits this process's environment and receives, on top of it, what the
        # launch declared: the platform's wiring and the resolved value of every reference the run
        # named. Resolved here rather than left to the child so a `file` backend's root, which the
        # child may not see, is read exactly once, by the process that has it.
        environment = {
            **os.environ,
            **self._env,
            **(env or {}),
            **{ref: self._resolver.resolve(ref) for ref in secret_refs},
        }
        process = subprocess.Popen([*self._command, "run", run_id], env=environment)
        self._running[run_id] = process
        return JobHandle(run_id=run_id, backend=BACKEND, identifier=str(process.pid))

    def status(self, run_id: str) -> JobState:
        process = self._running.get(run_id)
        if process is None:
            return JobState.UNKNOWN
        code = process.poll()
        if code is None:
            return JobState.RUNNING
        return JobState.SUCCEEDED if code == 0 else JobState.FAILED
