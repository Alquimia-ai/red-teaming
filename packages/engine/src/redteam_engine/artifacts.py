"""The control artifacts: the weakness profile and the exploitation report, kept in the store.

Both are the run's own instruments reporting on the run. The profile is how the control judge read
the assistant in order to decide what to press on; the report is what the search found when it
pressed. They are delivered because an operator wants to read them -- which principles broke most,
which categories of interaction broke the assistant reproducibly -- and they are labelled control
because their scores never enter the coverage. Coverage is planned, closed and failed, read off the
store's keys; nothing here can move it.

Each is written the moment it exists: the profile once profiling closes and passes the thin-profile
check, before the search starts, so a process that dies during the search still leaves the profile
it searched from; the report the moment the search returns. Append-only like everything else: a
relaunch that profiles again over the same traces finds the key taken and leaves it.
"""

from __future__ import annotations

import contextlib
from typing import Any

from redteam_store import layout
from redteam_store.codec import encode_json
from redteam_store.interface import ObjectAlreadyExists, ObjectStore


class ControlArtifacts:
    """Writes the profile and the report under the run's keys, once each."""

    def __init__(self, store: ObjectStore, run_id: str) -> None:
        self._store = store
        self._run_id = run_id

    def profile(self, result: Any) -> str:
        """The weakness profile with what the profiling reported about itself. Returns the key."""
        payload = {
            "profile": result.profile.model_dump(mode="json"),
            "overall_rate": result.overall_rate,
            "n_scoreable": result.n_scoreable,
            "n_ungraded": result.n_ungraded,
            "grading_methods": dict(result.grading_methods),
        }
        key = layout.profile(self._run_id)
        with contextlib.suppress(ObjectAlreadyExists):
            self._store.put(key, encode_json(payload), content_type="application/json")
        return key

    def exploit(self, report: Any) -> str:
        """The exploitation report, whole: the ranked categories with their queries, the queries
        over the threshold, and which implementation of each substitutable piece produced them.
        Returns the key."""
        key = layout.exploit(self._run_id)
        with contextlib.suppress(ObjectAlreadyExists):
            self._store.put(
                key, encode_json(report.model_dump(mode="json")), content_type="application/json"
            )
        return key
