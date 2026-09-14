"""Known internal dependencies must be checked rather than accepted as Any."""

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_correct_and_incorrect_collaborators_are_distinguished() -> None:
    source = """
from redteam_settings.config import Settings
from redteam_store.backends import build_store
from redteam_engine.conduct import conduct, Profiler, RecordingStats

def valid(profiler: Profiler, recorder: RecordingStats) -> None:
    build_store("memory", Settings())
    conduct(profiler, [], recorder, components={})
"""
    env = {
        **os.environ,
        "MYPYPATH": os.pathsep.join(
            str(p) for parent in ("apps", "packages") for p in (ROOT / parent).glob("*/src")
        ),
    }
    command = [sys.executable, "-m", "mypy", "--follow-imports=silent", "--no-error-summary", "-c"]
    good = subprocess.run([*command, source], cwd=ROOT, env=env, text=True, capture_output=True)
    assert good.returncode == 0, good.stdout + good.stderr
    bad = subprocess.run(
        [
            *command,
            source
            + '\nbuild_store("s3", object())\nconduct(object(), [], object(), components={})\n',
        ],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
    )
    assert bad.returncode == 1, bad.stdout + bad.stderr
    assert bad.stdout.count("[arg-type]") == 3, bad.stdout
