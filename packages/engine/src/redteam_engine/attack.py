"""Compose one run's profiling, exploitation, recording and dataset recovery.

PlanProfiler replays completed units and sends remaining units through the governed target.
A completed conduction checkpoint restores its dataset and provenance without another attack.
Concrete target adapters are constructed only behind the governed entrypoint."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from gaussia.core.target_assistant import TargetAssistant
from gaussia.schemas.roastme import FailureReport, Probe, ProfilerResult

from redteam_catalogue.contract import build_contract
from redteam_contracts.plan import Plan
from redteam_contracts.run_spec import RunSpec
from redteam_engine.artifacts import ControlArtifacts
from redteam_engine.attackers import AttackerUnbound, attackers_for
from redteam_engine.call_journal import CallJournal
from redteam_engine.conduct import conduct
from redteam_engine.dataset import RoastDataset, roast_dataset
from redteam_engine.execution import PlanProfiler, key_of
from redteam_engine.exploit import exploiter_for
from redteam_engine.governed import Budget, GovernedTarget, RateGate, SecretResolver, attackable
from redteam_engine.ledger import FailureLedger
from redteam_engine.planned import (
    AttackerProtocol,
    attackers_named_by,
    conducted_plugins,
    delivery_provenance,
    planned_deliveries,
)
from redteam_engine.recording import Recorder
from redteam_engine.resume import (
    closed_conduction,
    live_units,
    recorded_traces,
    remember_conduction,
    remember_exploit,
    remembered_exploit,
    responses_of,
)
from redteam_engine.roast import build_profiler
from redteam_judges.grading import grader_for
from redteam_store import contract as contract_store
from redteam_store import delivery as delivery_store
from redteam_store import layout
from redteam_store.interface import ObjectStore
from redteam_store.resume import RunDifference
from redteam_target.capabilities import CapabilityGate

DEFAULT_CONTEXT = "the assistant under evaluation"
DEFAULT_LANGUAGE = "english"
"""What the dataset's session says when the run declared no context. gaussia's own default for the
language; the phrase for the context says only what is known."""


@dataclass(frozen=True)
class Attacked:
    """What the attack left in the store, for the manifest."""

    components: dict[str, str]
    """What conduction reported about itself -- the target kind, the judge, whether the search ran,
    which model played each attacker, how the channel behaved."""

    dataset: str | None
    profile: str | None
    exploit: str | None
    """The keys of the deliverable and the two control artifacts, read off the store so an attempt
    that found conduction already closed reports them exactly as the one that closed it would."""


def attack(
    store: ObjectStore,
    spec: RunSpec,
    plan: Plan,
    diff: RunDifference,
    probes: Sequence[Mapping[str, Any]],
    *,
    resolver: SecretResolver,
    target: TargetAssistant | None = None,
    attackers: Mapping[str, AttackerProtocol] | None = None,
    started_at: float | None = None,
) -> Attacked:
    """Conduct the attack, or find it already conducted.

    Args:
        store: The run's store; every conversation lands here as it closes.
        spec: The frozen run spec.
        plan: The expanded plan -- every unit, in plan order.
        diff: The plan against the store, as `redteam_store.resume.difference` read it.
        probes: The run's probe set, as the records `probes.json` points at.
        resolver: Turns every `secret_ref` the spec names into a credential.
        target: An injected adapter -- a test's, or a rehearsal's. It still goes behind the same
            door: the seam is for substituting the transport, never for skipping the governance.
        attackers: Injected attackers, by id. Every id the plan names still has to be present.
        started_at: When the attempt began, on the monotonic clock, so the wall-clock ceiling
            counts generation too. `None` starts the clock here.
    """
    run_id = plan.run_id
    if store.exists(layout.dataset(run_id)) or store.exists(layout.recovery(run_id, "conduction")):
        return _attacked(store, run_id, closed_conduction(store, run_id))

    by_id: dict[str, dict[str, Any]] = {str(p["id"]): dict(p) for p in probes}
    connector = spec.connector
    budget = Budget(
        journal=CallJournal(store, run_id, spec.budget.max_target_calls),
        max_target_calls=spec.budget.max_target_calls,
        max_wall_seconds=spec.budget.max_wall_seconds,
    )
    if started_at is not None:
        budget.started_at = started_at
    # Generation already spent some of the run's wall clock; a run whose ceiling it exhausted stops
    # here rather than after the first call to the assistant.
    budget.charge_time()
    ledger = FailureLedger()
    # Failed markers do not close units: only completed traces can be replayed.
    replayed = recorded_traces(store, run_id, diff.closed)
    recorded = responses_of(replayed)
    live = live_units(plan.units, recorded)
    recorder = Recorder(store, run_id, by_id)

    # Delivery metadata is keyed to live units; attacker provenance includes the whole plan.
    versions = spec.catalogue_versions
    deliveries = delivery_store.merged(store, versions)
    needed = conducted_plugins(live, by_id, deliveries)
    planned = planned_deliveries(
        live,
        by_id,
        deliveries,
        delivery_store.objectives(store, versions, only=needed) if needed else {},
    )
    named = attackers_named_by(list(plan.units), by_id, deliveries)
    built: dict[str, AttackerProtocol] = dict(
        attackers if attackers is not None else attackers_for(spec, resolver, named)
    )
    if unbound := sorted(named - set(built)):
        raise AttackerUnbound(unbound)

    if target is not None:
        governed = GovernedTarget(
            target,
            gate=CapabilityGate(
                declared_capabilities=connector.declared_capabilities, safe_mode=connector.safe_mode
            ),
            budget=budget,
            rate=RateGate(min_interval_seconds=connector.min_interval_seconds),
            on_exchange=recorder,
            max_retries=connector.max_retries,
            ledger=ledger,
            attackers=built,
        )
    else:
        governed = attackable(
            connector,
            resolver,
            budget=budget,
            on_exchange=recorder,
            ledger=ledger,
            attackers=built,
        )

    # The Profiler's grading is control: it produces the weakness profile and steers the search. It
    # uses the judge the spec declared under one rule, so a run with no provider profiles with the
    # stand-in and says so. The contract is the one every selected catalogue carries, at the
    # versions the run froze -- read from the store, never off a file this image happens to ship.
    judge_key = resolver.resolve(spec.judge.secret_ref) if spec.judge.secret_ref else None
    grader, serving_path, judge_model = grader_for(spec.judge, judge_key)
    contract_spec, contract_digest = contract_store.shared(store, versions)
    contract = build_contract(contract_spec, grader)

    units = list(plan.units)
    handed = [Probe.model_validate(by_id[unit.probe_id]) for unit in units]
    if not handed:
        return _attacked(store, run_id, {"conduct": "nothing to conduct: the plan is empty"})

    # The adapter owns profiling order; replay bypasses the target budget and recorder.
    profiler = PlanProfiler(
        units,
        {probe.id: probe for probe in handed},
        recorded,
        {key_of(unit): delivery for unit, delivery in zip(live, planned, strict=True)},
        governed,
        recorder,
        lambda target: build_profiler(contract, target),
    )
    exploiter, why_not = exploiter_for(spec, contract, governed, resolver, store)

    context = spec.context
    remembered: dict[str, str] = {}

    def _build_dataset(
        result: ProfilerResult, report: FailureReport | None, searched: dict[str, str] | None
    ) -> list[RoastDataset]:
        if governed.fatal is not None:
            raise governed.fatal
        roast = roast_dataset(
            profiler.outcomes,
            report,
            run_id=run_id,
            assistant_id=str(connector.options.get("assistant_id") or connector.endpoint),
            context=context.domain if context is not None else DEFAULT_CONTEXT,
            language=context.language if context is not None else DEFAULT_LANGUAGE,
        )
        sessions: list[RoastDataset] = list(roast.sessions)
        if searched is not None:
            remember_exploit(store, run_id, searched, sessions)
        else:
            components, kept = remembered_exploit(store, run_id)
            remembered.update(components)
            sessions.extend(kept)
        return sessions

    conducted = conduct(
        profiler,
        handed,
        recorder,
        exploiter=exploiter,
        build_dataset=_build_dataset,
        ledger=ledger,
        artifacts=ControlArtifacts(store, run_id),
        components={
            "target": connector.kind,
            **(
                {
                    "realism_prior": spec.realism_prior,
                    "realism_prior_version": str(spec.realism_prior_version),
                    "realism_prior_digest": str(spec.realism_prior_digest),
                }
                if spec.realism_prior is not None
                else {}
            ),
            "contract_digest": contract_digest,
            "profile_judge_model": judge_model or "none",
            "profile_judge_serving_path": serving_path.value,
            **({"exploit": why_not} if why_not else {}),
            # Which model played each attacker id, for the attackers the plan names: a binding
            # nothing names had no part in any conversation and is not named beside them.
            **{f"attacker:{name}": attacker.model for name, attacker in sorted(built.items())},
        },
    )
    # An earlier attempt's search outranks this attempt's "skipped: already searched": the manifest
    # describes the run, and the run's search ran -- or failed -- once.
    components = {
        **conducted.components,
        **remembered,
        "conduct_replayed": str(profiler.replayed),
        **delivery_provenance(
            (trace.labels for trace in replayed.values()),
            conducted=governed.conducted,
            ended_early=governed.ended_early,
        ),
    }

    if governed.fatal is not None:
        raise governed.fatal
    remember_conduction(store, run_id, components, list(conducted.datasets))
    return _attacked(store, run_id, components)


def _attacked(store: ObjectStore, run_id: str, components: dict[str, str]) -> Attacked:
    def _present(key: str) -> str | None:
        return key if store.exists(key) else None

    return Attacked(
        components=components,
        dataset=_present(layout.dataset(run_id)),
        profile=_present(layout.profile(run_id)),
        exploit=_present(layout.exploit(run_id)),
    )
