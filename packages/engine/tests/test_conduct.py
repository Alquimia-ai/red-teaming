"""Profile, refuse a profile of the outage, exploit if there is anything to exploit with, and keep
the profile and the report as control artifacts."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

import pytest
from gaussia.schemas.roastme import Probe

from redteam_engine.conduct import Conducted, ProfileTooThin, conduct


@dataclass
class _Outcome:
    """What gaussia returns per exchange. `violation is None` is the ungraded one, and
    `ungraded_reason` is its account of why."""

    violation: float | None = 0.5
    ungraded_reason: str | None = None


@dataclass
class _Result:
    n_ungraded: int
    n_scoreable: int = 3
    overall_rate: float = 0.5
    grading_methods: dict[str, int] = field(default_factory=lambda: {"fake-marker": 3})
    profile: object = object()
    outcomes: list[_Outcome] = field(default_factory=list)


class _Profiler:
    def __init__(self, n_ungraded: int = 0, reason: str | None = None) -> None:
        self.n_ungraded = n_ungraded
        self.reason = reason
        self.seen: list[Probe] = []

    def profile(self, probes: Sequence[Probe]) -> _Result:
        self.seen = list(probes)
        return _Result(
            n_ungraded=self.n_ungraded,
            n_scoreable=len(probes),
            outcomes=[
                _Outcome(violation=None, ungraded_reason=self.reason)
                for _ in range(self.n_ungraded)
            ],
        )


@dataclass
class _Report:
    categories: list[object] = field(default_factory=lambda: [object(), object()])
    queries_over_threshold: list[object] = field(default_factory=list)
    components: dict[str, str] = field(default_factory=lambda: {"search": "AttributeIteration"})


class _Exploiter:
    def __init__(self) -> None:
        self.profiled_from: object = None

    def exploit(self, profile: object) -> _Report:
        self.profiled_from = profile
        return _Report()


class _Recorder:
    def __init__(self) -> None:
        self.phases: list[str] = []
        self.written = 4
        self.beyond_plan = 1

    @property
    def phase(self) -> str:
        return self.phases[-1] if self.phases else ""

    @phase.setter
    def phase(self, value: str) -> None:
        self.phases.append(value)


class _Artifacts:
    def start_exploit(self) -> None:
        pass

    """Remembers what it was asked to keep, in order."""

    def __init__(self) -> None:
        self.kept: list[tuple[str, object]] = []

    def profile(self, result: object) -> str:
        self.kept.append(("profile", result))
        return "runs/r/profile.json"

    def exploit(self, report: object) -> str:
        self.kept.append(("exploit", report))
        return "runs/r/exploit.json"


def _probes(n: int) -> list[Probe]:
    return [Probe(id=f"p{i}", query=f"q{i}?", strategy="s") for i in range(n)]


def test_the_profiler_is_handed_exactly_the_probes_it_was_given_in_order() -> None:
    profiler = _Profiler()
    probes = _probes(3)
    conduct(profiler, probes, _Recorder(), components={})
    assert [p.id for p in profiler.seen] == ["p0", "p1", "p2"]


def test_an_outage_of_one_kind_is_refused_as_that_kind_before_the_generic_count() -> None:
    """`ProfileTooThin` says how many; it never says what. When the ledger shows one kind behind
    the failures, the run dies as that kind, with the target's words in the record."""
    from http import HTTPStatus

    from redteam_contracts.failure import UNAUTHORIZED, TransportFailure
    from redteam_engine.errors import TargetUnauthorized
    from redteam_engine.ledger import FailureLedger

    ledger = FailureLedger()
    for _ in range(3):
        ledger.record(
            TransportFailure(
                kind=UNAUTHORIZED, message="bad key", error_type="X", status=HTTPStatus.UNAUTHORIZED
            )
        )

    with pytest.raises(TargetUnauthorized, match="3 of 4 exchanges failed as 'unauthorized'"):
        conduct(_Profiler(n_ungraded=3), _probes(4), _Recorder(), components={}, ledger=ledger)


def test_mixed_failures_fall_through_to_the_generic_refusal() -> None:
    from redteam_contracts.failure import RATE_LIMITED, SERVER_ERROR, TransportFailure
    from redteam_engine.ledger import FailureLedger

    ledger = FailureLedger()
    for kind in (RATE_LIMITED, SERVER_ERROR):
        ledger.record(TransportFailure(kind=kind, message="m", error_type="X"))

    with pytest.raises(ProfileTooThin):
        conduct(_Profiler(n_ungraded=2), _probes(4), _Recorder(), components={}, ledger=ledger)


def test_the_channel_s_behaviour_is_provenance_in_the_components() -> None:
    from redteam_contracts.failure import RATE_LIMITED, TransportFailure
    from redteam_engine.ledger import FailureLedger

    ledger = FailureLedger()
    ledger.recovered = 2
    ledger.record(TransportFailure(kind=RATE_LIMITED, message="m", error_type="X"))

    conducted = conduct(_Profiler(), _probes(8), _Recorder(), components={}, ledger=ledger)

    assert conducted.components["transport_recovered"] == "2"
    assert conducted.components["transport_failed"] == "rate_limited=1"


def test_a_profile_of_the_outage_is_refused() -> None:
    """gaussia: 'if this number is large, stop and fix the adapter -- the profile is being computed
    over whatever survived'."""
    with pytest.raises(ProfileTooThin, match="describe an outage"):
        conduct(_Profiler(n_ungraded=2), _probes(4), _Recorder(), components={})


def test_the_refusal_says_which_component_failed_rather_than_blaming_the_adapter() -> None:
    """gaussia records the real reason on every ungraded exchange -- it separates "the target
    reported the exchange failed" from "the judge failed: ..." -- and the refusal has to read it. A
    diagnosis that names the wrong component costs another full run against somebody's assistant
    to disprove."""
    with pytest.raises(ProfileTooThin) as caught:
        conduct(
            _Profiler(n_ungraded=3, reason="the judge failed: ReadTimeout: provider timed out"),
            _probes(4),
            _Recorder(),
            components={},
        )

    message = str(caught.value)
    assert "the judge failed" in message, "the reason gaussia recorded never reached the reader"
    assert "3x" in message, "identical failures are counted rather than repeated"
    assert "adapter" not in message, "it must not name a component it has not established"


def test_an_ungraded_exchange_with_no_recorded_reason_still_refuses() -> None:
    """The count alone is enough to refuse. Missing reasons must not turn the guard into a crash."""
    with pytest.raises(ProfileTooThin, match="no reason recorded"):
        conduct(_Profiler(n_ungraded=2), _probes(4), _Recorder(), components={})


def test_a_refused_profile_is_not_kept_as_an_artifact() -> None:
    """A profile of the outage is not the weakness profile, and the store only appends: written, it
    would stand in the way of the profile the relaunch computes over the real answers."""
    artifacts = _Artifacts()
    with pytest.raises(ProfileTooThin):
        conduct(
            _Profiler(n_ungraded=2), _probes(4), _Recorder(), components={}, artifacts=artifacts
        )
    assert artifacts.kept == []


def test_no_exploiter_is_recorded_rather_than_silently_skipped() -> None:
    """A manifest that does not say the search never ran reads exactly like one for a run whose
    search found nothing."""
    out = conduct(_Profiler(), _probes(2), _Recorder(), exploiter=None, components={"target": "t"})
    assert out.components["exploit"].startswith("skipped")
    assert out.components["target"] == "t"
    assert out.components["profile_n_scoreable"] == "2"
    assert out.exploit_key is None


def test_the_exploiter_runs_from_the_profile_and_the_recorder_switches_phase() -> None:
    recorder = _Recorder()
    exploiter = _Exploiter()
    out = conduct(_Profiler(), _probes(2), recorder, exploiter=exploiter, components={})

    assert exploiter.profiled_from is not None
    assert out.components["exploit"] == "ran"
    assert out.components["exploit_n_categories"] == "2"
    assert out.components["exploit_search"] == "AttributeIteration"


def test_the_profile_is_kept_before_the_search_and_the_report_the_moment_it_exists() -> None:
    """A process that dies during the search still leaves the profile it searched from; the report
    is kept as a control artifact and its key crosses out, never its content."""
    artifacts = _Artifacts()
    profiler = _Profiler()
    exploiter = _Exploiter()

    out = conduct(
        profiler, _probes(2), _Recorder(), exploiter=exploiter, components={}, artifacts=artifacts
    )

    assert [what for what, _ in artifacts.kept] == ["profile", "exploit"]
    assert isinstance(artifacts.kept[0][1], _Result)
    assert isinstance(artifacts.kept[1][1], _Report)
    assert out.profile_key == "runs/r/profile.json"
    assert out.exploit_key == "runs/r/exploit.json"


def test_what_crosses_out_carries_counts_and_never_the_report() -> None:
    out = conduct(_Profiler(), _probes(2), _Recorder(), exploiter=_Exploiter(), components={})
    assert isinstance(out, Conducted)
    assert out.n_planned_traces == 3
    assert out.n_generated_traces == 1
    for value in out.components.values():
        assert "queries_over_threshold" not in value
    assert not {k for k in out.components if "categor" in k and k != "exploit_n_categories"}


def test_components_carry_thresholds_as_provenance_not_as_fields() -> None:
    """A stringly-typed record of what ran, so nothing downstream can divide by it."""
    out: Any = conduct(_Profiler(), _probes(1), _Recorder(), components={})
    assert all(isinstance(v, str) for v in out.components.values())


def test_a_channel_that_dies_during_the_search_ends_the_attempt_rather_than_the_search() -> None:
    """A refused credential mid-search is the policy aborting the run, not the search failing.
    Swallowed by the search's own recovery, the run would close COMPLETE over a search that never
    happened and could never be resumed under its id. It escapes, into the failure record."""
    from http import HTTPStatus

    from redteam_contracts.failure import UNAUTHORIZED, TransportFailure
    from redteam_engine.errors import TargetUnauthorized

    class _Refused:
        def exploit(self, profile: object) -> object:
            raise TargetUnauthorized(
                TransportFailure(
                    kind=UNAUTHORIZED,
                    message="bad key",
                    error_type="X",
                    status=HTTPStatus.UNAUTHORIZED,
                )
            )

    with pytest.raises(TargetUnauthorized):
        conduct(_Profiler(), _probes(2), _Recorder(), exploiter=_Refused(), components={})


def test_a_search_that_fails_is_recorded_and_does_not_lose_the_profile() -> None:
    """A 429 from the generator's provider on category four is not a reason to lose the profile
    traces already paid for. 'The search failed and why' and 'the search found nothing' are
    different claims, and both stay readable in the manifest."""

    class _Broken:
        def exploit(self, profile: object) -> object:
            raise RuntimeError("TooManyRequests: provider returned error")

    artifacts = _Artifacts()
    out = conduct(
        _Profiler(),
        _probes(2),
        _Recorder(),
        exploiter=_Broken(),
        components={},
        artifacts=artifacts,
    )
    assert out.components["exploit"].startswith("failed: RuntimeError")
    assert "exploit_n_categories" not in out.components
    assert out.components["profile_n_scoreable"] == "2"
    assert [what for what, _ in artifacts.kept] == ["profile"], "no report to keep"
    assert out.exploit_key is None


def test_the_dataset_builder_is_told_how_the_search_went() -> None:
    """What the search reported about itself travels into the dataset builder with the report, so
    the resume path can keep it beside the session: a relaunch that finds the marker has to carry
    the search's provenance into the manifest, and a search that failed has to be remembered as much
    as one that ran, or the relaunch searches again."""
    seen: list[Any] = []

    def _build(result: Any, report: Any, searched: Any) -> list[Any]:
        seen.append(searched)
        return []

    class _Broken:
        def exploit(self, profile: object) -> object:
            raise RuntimeError("429")

    for exploiter in (_Exploiter(), _Broken(), None):
        conduct(
            _Profiler(),
            _probes(2),
            _Recorder(),
            exploiter=exploiter,
            build_dataset=_build,
            components={},
        )

    ran, failed, skipped = seen
    assert ran == {
        "exploit": "ran",
        "exploit_n_categories": "2",
        "exploit_search": "AttributeIteration",
    }
    assert failed == {"exploit": "failed: RuntimeError: 429"}
    assert skipped is None, "no search was attempted, so there is nothing to remember"
