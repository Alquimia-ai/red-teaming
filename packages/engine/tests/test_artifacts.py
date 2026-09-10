"""The weakness profile and the exploitation report are kept as control artifacts, once each."""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from gaussia.schemas.roastme import AssistantProfile, WeaknessEntry

from redteam_engine.artifacts import ControlArtifacts
from redteam_store import layout
from redteam_store.memory import MemoryObjectStore

RUN = "run-art"


@dataclass
class _Result:
    profile: AssistantProfile
    overall_rate: float = 0.25
    n_scoreable: int = 4
    n_ungraded: int = 0
    grading_methods: dict[str, int] = field(default_factory=lambda: {"fake-marker": 4})


@dataclass
class _Report:
    """Only what the artifact writer reads: something that dumps."""

    payload: dict[str, object]

    def model_dump(self, *, mode: str) -> dict[str, object]:
        return dict(self.payload)


def _result() -> _Result:
    return _Result(
        profile=AssistantProfile(
            weaknesses=[
                WeaknessEntry(
                    principle="no_invention",
                    descriptor="leans on a product the base does not contain",
                    rate=0.5,
                    n=2,
                    standard_error=0.35,
                )
            ]
        )
    )


def test_the_profile_is_written_under_its_key_with_what_profiling_reported() -> None:
    store = MemoryObjectStore()

    key = ControlArtifacts(store, RUN).profile(_result())

    assert key == layout.profile(RUN)
    written = json.loads(store.get(key))
    assert written["profile"]["weaknesses"][0]["principle"] == "no_invention"
    assert written["n_scoreable"] == 4 and written["overall_rate"] == 0.25
    assert written["grading_methods"] == {"fake-marker": 4}


def test_the_report_is_written_whole_under_its_key() -> None:
    store = MemoryObjectStore()
    report = _Report({"categories": [{"score": 0.9}], "components": {"search": "x"}})

    key = ControlArtifacts(store, RUN).exploit(report)

    assert key == layout.exploit(RUN)
    assert json.loads(store.get(key)) == report.payload


def test_a_second_attempt_leaves_the_first_artifact_standing() -> None:
    """The store appends: a relaunch that profiles again over the same traces finds the key taken
    and the first account stands."""
    store = MemoryObjectStore()
    artifacts = ControlArtifacts(store, RUN)
    artifacts.profile(_result())
    later = _result()
    later.overall_rate = 0.9

    artifacts.profile(later)

    assert json.loads(store.get(layout.profile(RUN)))["overall_rate"] == 0.25
