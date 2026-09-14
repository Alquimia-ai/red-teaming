"""Profile, reject unusable profiles, and optionally exploit the resulting weaknesses.

Profile and exploitation scores are control artifacts, never coverage measurements. Persist
those artifacts as they become available; return counts, provenance and dataset sessions."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Protocol

from gaussia.schemas.roastme import AssistantProfile, FailureReport, Probe, ProfilerResult

from redteam_engine.checkpoints import RecoveryIncomplete
from redteam_engine.dataset import RoastDataset
from redteam_engine.errors import TargetFailure
from redteam_engine.governed import BudgetExhausted
from redteam_engine.ledger import FailureLedger

UNGRADED_ALARM_RATIO = 0.25
"""Above this share of failed exchanges the run stops rather than profiling over the survivors.

gaussia says it plainly: "if this number is large, stop and fix the adapter -- the profile is being
computed over whatever survived." A profile built on a quarter-broken run is not a weak profile, it
is a profile of the outage.
"""


class ProfileTooThin(RuntimeError):
    """Too many exchanges failed for the profile to describe the assistant."""


@dataclass(frozen=True)
class Conducted:
    """What crosses out of conduction. Deliberately not the report."""

    components: dict[str, str]
    """Which implementation of each substitutable piece ran, and the thresholds in force.

    Provenance rather than measurement, which is why it may cross. Two of the three shipped
    Exploiter collaborators are gaussia's own construction rather than the paper's, so a weak result
    has to be attributable to the part that can be swapped instead of to the method.
    """

    n_probes: int
    n_ungraded: int
    n_planned_traces: int
    """Conversations written under a key the plan derived -- the profiling exchanges."""

    n_generated_traces: int
    """Conversations written beyond the plan -- the search's own. Evidence, never coverage."""

    datasets: tuple[RoastDataset, ...] = ()
    """The attack dataset, one session per replica. Built inside conduction from the Profiler's
    result and the Exploiter's report, because those two are what it is made of."""

    profile_key: str | None = None
    """Where the weakness profile was written, when it was."""

    exploit_key: str | None = None
    """Where the exploitation report was written, when the search ran."""


def _why_ungraded(result: ProfilerResult) -> str:
    """The distinct reasons exchanges went ungraded, most common first.

    gaussia records one per exchange and separates the two cases that matter -- "the target
    reported the exchange failed" from "the judge failed: ..." -- and a refusal that read neither
    would send the reader at the wrong component: a run dying with "fix the adapter" while every
    one of its traces held a real answer and the judge was what raised costs another full run to
    find out.

    Capped, because a provider that fails once fails identically fifty times and the message is
    read in a log line.
    """
    from collections import Counter

    reasons = Counter(
        str(outcome.ungraded_reason or "no reason recorded")
        for outcome in result.outcomes
        if outcome.violation is None
    )
    if not reasons:
        return "no reason recorded"
    return "; ".join(f"{count}x {reason[:160]}" for reason, count in reasons.most_common(3))


class Profiler(Protocol):
    def profile(self, probes: Sequence[Probe]) -> ProfilerResult: ...


class Exploitation(Protocol):
    def exploit(self, profile: AssistantProfile) -> FailureReport: ...


class RecordingStats(Protocol):
    @property
    def written(self) -> int: ...
    @property
    def beyond_plan(self) -> int: ...


class Artifacts(Protocol):
    def profile(self, result: ProfilerResult) -> str: ...
    def start_exploit(self) -> None: ...
    def exploit(self, report: FailureReport) -> str: ...


DatasetBuilder = Callable[
    [ProfilerResult, FailureReport | None, dict[str, str] | None], Sequence[RoastDataset]
]


def conduct(
    profiler: Profiler,
    probes: list[Probe],
    recorder: RecordingStats,
    *,
    exploiter: Exploitation | None = None,
    build_dataset: DatasetBuilder | None = None,
    components: dict[str, str],
    ungraded_alarm_ratio: float = UNGRADED_ALARM_RATIO,
    ledger: FailureLedger | None = None,
    artifacts: Artifacts | None = None,
) -> Conducted:
    """Profile the complete plan, persist control artifacts and optionally search it.

    The profiler handles replay; recorder supplies persisted trace counts. A dominant transport
    failure or excessive ungraded ratio rejects the profile before search. Artifacts retain the
    profile before exploitation and the report on success. The dataset callback receives search
    provenance, including failure or absence, so recovery can preserve the original evidence.
    """
    result = profiler.profile(probes)

    total = max(len(probes), 1)
    if ledger is not None and (typed := ledger.verdict(total, ungraded_alarm_ratio)) is not None:
        raise typed
    if result.n_ungraded / total > ungraded_alarm_ratio:
        raise ProfileTooThin(
            f"{result.n_ungraded} of {total} exchanges could not be graded, so the profile would "
            f"describe an outage rather than the assistant. By reason: {_why_ungraded(result)}."
        )

    # The profile is a control artifact and is kept the moment it is known to be worth keeping:
    # after the thin-profile check, before the search, so a process that dies searching still
    # leaves the profile it searched from.
    profile_key = artifacts.profile(result) if artifacts is not None else None

    recorded = {
        **components,
        "profile_n_scoreable": str(result.n_scoreable),
        "profile_n_ungraded": str(result.n_ungraded),
        "profile_grading_methods": ",".join(
            f"{k}={v}" for k, v in sorted(result.grading_methods.items())
        ),
    }
    if ledger is not None:
        # How the channel behaved, as provenance: exchanges a retry rescued, and the kinds that
        # were given up on. A run whose profile is thin because the target rate-limited for an
        # hour and one whose assistant answered every probe are different runs, and the manifest
        # has to let a reader tell them apart.
        recorded["transport_recovered"] = str(ledger.recovered)
        recorded["transport_failed"] = ",".join(
            f"{kind}={count}" for kind, count in sorted(ledger.by_kind().items())
        )

    report = None
    exploit_key: str | None = None
    if exploiter is None:
        # The caller may already know why -- the piece the run did not declare, or an earlier
        # attempt that already searched -- and its reason is more specific than this default.
        recorded.setdefault("exploit", "skipped: no generator model declared")
    else:
        if artifacts is not None:
            artifacts.start_exploit()
        try:
            report = exploiter.exploit(result.profile)
        except (TargetFailure, BudgetExhausted, RecoveryIncomplete):
            # The channel to the assistant died -- a refused credential, say -- and the policy said
            # the run cannot continue through it. That is an attempt dying, not a search failing:
            # swallowed here, the run would close COMPLETE over a search that never happened and
            # could never be resumed under its id. It escapes, and dies into the failure record.
            raise
        except Exception as failed:
            # The Profiler's own discipline, applied to the search: a 429 from the generator's
            # provider on category four is not a reason to lose the profile traces already paid
            # for and written. The manifest says the search failed and why, which is a different
            # claim from "the search found nothing", and both have to stay readable.
            recorded["exploit"] = f"failed: {type(failed).__name__}: {str(failed)[:160]}"
            report = None
        else:
            # The report is kept as a control artifact and turned into the dataset; what crosses
            # out of here is which piece ran and how many categories the search returned -- never
            # the ranking, never the queries over a threshold.
            exploit_key = artifacts.exploit(report) if artifacts is not None else None
            recorded["exploit"] = "ran"
            recorded["exploit_n_categories"] = str(len(report.categories))
            recorded.update({f"exploit_{k}": str(v) for k, v in report.components.items()})

    # The dataset is built here, from the result and the report. What the search said about itself
    # goes along -- `ran` with its categories, or `failed` and why -- for the checkpoint the
    # builder keeps; None when there was no search to remember.
    searched = (
        {k: v for k, v in recorded.items() if k.startswith("exploit")}
        if exploiter is not None
        else None
    )
    datasets = tuple(build_dataset(result, report, searched)) if build_dataset is not None else ()

    return Conducted(
        components=recorded,
        n_probes=len(probes),
        n_ungraded=result.n_ungraded,
        n_planned_traces=recorder.written - recorder.beyond_plan,
        n_generated_traces=recorder.beyond_plan,
        datasets=datasets,
        profile_key=profile_key,
        exploit_key=exploit_key,
    )
