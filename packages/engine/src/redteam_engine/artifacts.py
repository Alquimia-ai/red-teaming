"""Persist the weakness profile and exploitation report as immutable control artifacts.

Save a usable profile before searching and the report when search returns. Their scores do not
enter coverage, which is derived from planned, completed and failed work-unit keys."""

from __future__ import annotations

import contextlib

from gaussia.schemas.roastme import FailureReport, ProfilerResult

from redteam_store import layout
from redteam_store.codec import encode_json
from redteam_store.interface import ObjectAlreadyExists, ObjectStore


class ControlArtifacts:
    """Writes the profile and the report under the run's keys, once each."""

    def __init__(self, store: ObjectStore, run_id: str) -> None:
        self._store = store
        self._run_id = run_id

    def profile(self, result: ProfilerResult) -> str:
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

    def start_exploit(self) -> None:
        from redteam_engine.checkpoints import put_same

        put_same(self._store, layout.recovery(self._run_id, "exploit-started"), b'{"version":1}')

    def exploit(self, report: FailureReport) -> str:
        """The exploitation report, whole: the ranked categories with their queries, the queries
        over the threshold, and which implementation of each substitutable piece produced them.
        Returns the key."""
        key = layout.exploit(self._run_id)
        with contextlib.suppress(ObjectAlreadyExists):
            self._store.put(
                key, encode_json(report.model_dump(mode="json")), content_type="application/json"
            )
        return key
