"""Conducting profile-then-exploit, with the governance around it.

The search itself is gaussia's and is not reimplemented here. What the engine owns is everything
gaussia does not govern: the gates before the first turn, the budget, recording each exchange as it
closes, keeping the profile and the report as control artifacts, and knowing when the profile is too
thin to build on.

**What crosses out of conduction is provenance, never a measurement.** Two gradings run inside a
run and both are control: the Profiler's produces the weakness profile the Exploiter reads, and the
Exploiter's ranks categories. Both may threshold and average -- `tau` and `eta` are thresholds --
and both are kept in the store as control artifacts, labelled so, because an operator wants to read
them. What they must never do is enter the coverage: a reader who finds `tau` in the config and a
score in the manifest would divide one by the other, and the manifest would then claim something
the run never measured. So `Conducted` carries counts and components, and no report; the report
reaches the store through `ControlArtifacts` and the manifest names its key.

The evidence -- every conversation -- is already in the store by the time this returns, written by
the recorder as each exchange closed, which is why nothing here has to carry it out.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from gaussia.schemas.roastme import Probe

from redteam_engine.errors import TargetFailure
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

    datasets: tuple[Any, ...] = ()
    """The attack dataset, one session per replica. Built inside conduction from the Profiler's
    result and the Exploiter's report, because those two are what it is made of."""

    profile_key: str | None = None
    """Where the weakness profile was written, when it was."""

    exploit_key: str | None = None
    """Where the exploitation report was written, when the search ran."""


def _why_ungraded(result: Any) -> str:
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
        for outcome in getattr(result, "outcomes", ())
        if outcome.violation is None
    )
    if not reasons:
        return "no reason recorded"
    return "; ".join(f"{count}x {reason[:160]}" for reason, count in reasons.most_common(3))


def conduct(
    profiler: Any,
    probes: list[Probe],
    recorder: Any,
    *,
    exploiter: Any = None,
    build_dataset: Any = None,
    components: dict[str, str],
    ungraded_alarm_ratio: float = UNGRADED_ALARM_RATIO,
    ledger: FailureLedger | None = None,
    artifacts: Any = None,
) -> Conducted:
    """Run the profiler, check the profile is worth building on, run the exploiter if there is one.

    Args:
        ledger: What the governed target recorded about every failed exchange. Read before the
            thin-profile check: when one kind of transport failure explains the outage, the run
            dies as that kind -- `unauthorized`, `rate_limited` -- with the target's own words in
            the record, rather than as a count of ungraded exchanges that sends the reader to open
            thirty traces to learn they were all a 401. The generic refusal stays for the mixed
            case, and for a run conducted without a ledger.
        profiler: gaussia's, built over the governed target.
        probes: One per unit of the **whole** plan, in plan order. The target behind the profiler
            answers the closed ones from their traces and sends the pending ones live, so the
            profile and the thin-profile ratio describe the run and not this attempt's tail.
        recorder: The `on_exchange` hook already installed on the target. Its phase is switched
            here, because only conduction knows which stage is sending.
        exploiter: gaussia's, or `None` when the run declared no generator to search with. Absent
            is recorded rather than silently skipped: a manifest that does not say the search never
            ran reads exactly like one for a run whose search found nothing.
        build_dataset: Given the Profiler's result, the Exploiter's report (or None) and what the
            search reported about itself (or None when no search was attempted), returns the attack
            dataset. Supplied by the caller closed over the run-level inputs -- the plan's units,
            the context -- that conduction does not carry. Called here so the caller can checkpoint
            the search however it went: a relaunch must not search again, and must still carry the
            search's provenance.
        components: What the caller knows about the pieces -- the target kind, the judge.
        artifacts: Where the profile and the report are kept -- `ControlArtifacts` over the run's
            store. `None` keeps neither, which is only sensible in a test.
    """
    from redteam_engine.recording import EXPLOIT, PROFILE

    recorder.phase = PROFILE
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
        recorder.phase = EXPLOIT
        try:
            report = exploiter.exploit(result.profile)
        except TargetFailure:
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
