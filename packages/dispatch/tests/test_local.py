"""A runner as a subprocess: one per run, refused while alive, and its liveness read off the
process."""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

import pytest

from redteam_dispatch import AlreadyRunning, JobState
from redteam_dispatch.local import LocalSubprocessDispatcher

EXIT_BY_ID = (
    sys.executable,
    "-c",
    "import sys; sys.exit(0 if sys.argv[2].endswith('ok') else 3)",
)
"""A stand-in runner: `<python> -c ... run <run_id>` succeeds for an id ending in `ok`."""

SLEEPS = (sys.executable, "-c", "import time; time.sleep(30)")

WRITES_ITS_SECRET = (
    sys.executable,
    "-c",
    "import os, pathlib; pathlib.Path(os.environ['OUT']).write_text(os.environ['TARGET_KEY'])",
)


class _Resolver:
    def __init__(self) -> None:
        self.asked: list[str] = []

    def resolve(self, ref: str) -> str:
        self.asked.append(ref)
        return f"resolved-{ref}"


def _wait(dispatcher: LocalSubprocessDispatcher, run_id: str) -> None:
    process = dispatcher._running[run_id]
    process.wait(timeout=30)


def test_the_process_is_handed_the_run_id_and_its_exit_code_is_its_state() -> None:
    dispatcher = LocalSubprocessDispatcher(_Resolver(), command=EXIT_BY_ID)

    good = dispatcher.launch("run-ok")
    bad = dispatcher.launch("run-bad")
    _wait(dispatcher, "run-ok")
    _wait(dispatcher, "run-bad")

    assert good.backend == "local_subprocess" and good.identifier.isdigit()
    assert bad.identifier != good.identifier
    assert dispatcher.status("run-ok") is JobState.SUCCEEDED
    assert dispatcher.status("run-bad") is JobState.FAILED
    assert dispatcher.status("run-nobody-launched") is JobState.UNKNOWN


def test_a_run_is_refused_while_its_process_is_alive_and_allowed_once_it_is_not() -> None:
    dispatcher = LocalSubprocessDispatcher(_Resolver(), command=SLEEPS)
    dispatcher.launch("run-1")
    try:
        assert dispatcher.status("run-1") is JobState.RUNNING
        with pytest.raises(AlreadyRunning, match="redteam-run-run-1"):
            dispatcher.launch("run-1")
    finally:
        process = dispatcher._running["run-1"]
        process.kill()
        process.wait(timeout=10)

    assert dispatcher.status("run-1") is JobState.FAILED, "killed is not succeeded"
    relaunched = dispatcher.launch("run-1")
    try:
        assert relaunched.identifier != str(process.pid)
    finally:
        dispatcher._running["run-1"].kill()
        dispatcher._running["run-1"].wait(timeout=10)


def test_the_secrets_the_launch_names_reach_the_process_resolved(tmp_path: Path) -> None:
    """The subprocess is handed the value, resolved by the process that has the backend -- a `file`
    root the child may not see is read exactly once, here."""
    out = tmp_path / "seen"
    resolver = _Resolver()
    dispatcher = LocalSubprocessDispatcher(resolver, command=WRITES_ITS_SECRET)

    dispatcher.launch("run-1", env={"OUT": str(out)}, secret_refs=("TARGET_KEY",))
    _wait(dispatcher, "run-1")

    assert resolver.asked == ["TARGET_KEY"]
    assert out.read_text() == "resolved-TARGET_KEY"
    assert dispatcher.status("run-1") is JobState.SUCCEEDED


def test_an_id_outside_the_rule_is_refused_before_anything_starts() -> None:
    dispatcher = LocalSubprocessDispatcher(_Resolver(), command=EXIT_BY_ID)
    with pytest.raises(ValueError, match="does not follow the rule"):
        dispatcher.launch("Run_1")
    assert dispatcher._running == {}


def test_status_reads_the_process_rather_than_remembering() -> None:
    dispatcher = LocalSubprocessDispatcher(_Resolver(), command=EXIT_BY_ID)
    dispatcher.launch("run-ok")
    deadline = time.monotonic() + 30
    while dispatcher.status("run-ok") is JobState.RUNNING and time.monotonic() < deadline:
        time.sleep(0.05)
    assert dispatcher.status("run-ok") is JobState.SUCCEEDED
    assert isinstance(dispatcher._running["run-ok"], subprocess.Popen)
