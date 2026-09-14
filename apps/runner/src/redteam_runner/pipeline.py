"""The shape of a run, seen from the runner.

    spec.json (frozen by the API)   -> the request, read once
    probes.json  -> blobs/{digest}  -> generation, in this process, or the pinned set
    expand -> difference            -> the plan, and what of it the store already holds
    attack                          -> traces/..., profile.json, exploit.json, dataset.json
    manifest.json                   -> the run closed; the webhook says where to read

If the process dies anywhere, resumption needs no new mechanism: `probes.json`, the traces, the
control artifacts and the dataset are keys in the store, so their existence is the record. The next
launch of the same run id reads what is there and does the rest.

**A failure is not a closed run.** An exception anywhere after the attempt began -- generation
refused as much as the attack -- writes a failure record under `runs/{id}/failures/` and exits
non-zero; it never writes `manifest.json`, whose existence means COMPLETE to every reader of the
store. The platform's retry policy relaunches, and the relaunch resumes from the difference.
"""

from __future__ import annotations

import json
import time
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
from gaussia.core.target_assistant import TargetAssistant

from redteam_contracts.kb import KnowledgeBase
from redteam_contracts.manifest import RunPhase
from redteam_contracts.plan import PlannedProbe, expand
from redteam_contracts.run_spec import RunSpec
from redteam_delivery import Delivery, deliver, idempotency_key
from redteam_engine.assemble import begin_attempt, write_failure, write_manifest
from redteam_engine.attack import attack
from redteam_engine.call_journal import CallJournal
from redteam_engine.planned import AttackerProtocol
from redteam_probes.generate_run import generate_for
from redteam_probes.request import GenerationReport, GenerationRequest
from redteam_runner.wiring import brain_registry, generator_for
from redteam_secrets.resolver import SecretResolver, build_resolver
from redteam_settings.config import Settings
from redteam_store import layout, versioned
from redteam_store.backends import build_store
from redteam_store.interface import ObjectStore
from redteam_store.resume import difference


@dataclass(frozen=True)
class RunOutcome:
    run_id: str
    phase: RunPhase
    n_traces: int
    resumed: int
    """How many units were already closed when this attempt started. Non-zero means it is a retry,
    and that number is the difference doing its job."""

    record: str | None
    """The key the consumer reads: the manifest when the run closed, the failure record when this
    attempt died, nothing for a dry run."""

    delivery: Delivery | None = None
    """What became of the webhook, for the log. Never a reason to fail."""


def execute(
    run_id: str,
    *,
    settings: Settings,
    dry_run: bool = False,
    store: ObjectStore | None = None,
    resolver: SecretResolver | None = None,
    target: TargetAssistant | None = None,
    attackers: Mapping[str, AttackerProtocol] | None = None,
    knowledge_base: KnowledgeBase | None = None,
    webhook_client: httpx.Client | None = None,
) -> RunOutcome:
    """Run to completion, or report what it got to.

    The store, the resolver, the target, the attackers, the knowledge base and the webhook client
    are injectable. Not for test convenience alone: a pipeline whose collaborators can only be
    replaced by patching module globals has no seam. Production passes none of them and gets the
    configured ones.
    """
    store = store or build_store(settings.store_backend.value, settings)
    raw = store.get(layout.spec(run_id))
    spec = RunSpec.model_validate_json(raw)

    if dry_run:
        return RunOutcome(run_id, RunPhase.ACCEPTED, 0, 0, None)

    # A manifest means the run closed. The same rule the trace keys follow, applied to the run: the
    # artifact existing *is* the record that the work is done, so a runner launched for a finished
    # run has nothing to do rather than something to redo.
    if store.exists(layout.manifest(run_id)):
        closed = _n_traces(store, run_id)
        return RunOutcome(run_id, RunPhase.COMPLETE, closed, closed, layout.manifest(run_id))

    resolver = resolver or _resolver(settings)
    # Announced before anything else, under the id a failure record would carry: the status reads
    # `failed` only while the newest attempt is the one that died, so a relaunch that has begun
    # reads as what it is doing rather than as the death it is recovering from.
    attempt = begin_attempt(store, run_id=run_id)
    started = time.monotonic()
    resumed = 0
    try:
        if not store.exists(layout.dataset(run_id)) and not store.exists(
            layout.recovery(run_id, "conduction")
        ):
            CallJournal(store, run_id, spec.budget.max_target_calls)
        report = _generate(store, spec, settings, resolver, knowledge_base)
        probes = [dict(p) for p in json.loads(store.get(layout.blob(report.probes_digest)))]
        # The versions generation read from are the ones the plan is conducted against: the spec's
        # where the API froze them, generation's own for a spec nobody accepted.
        conducted = spec.model_copy(update={"catalogue_versions": dict(report.catalogue_versions)})
        plan = expand(
            run_id,
            [
                PlannedProbe(
                    probe_id=str(p["id"]), plugin=p.get("plugin"), strategy=p.get("strategy")
                )
                for p in probes
            ],
            {"catalogues": list(spec.catalogues)},
            spec.replicas,
        )
        diff = difference(store, plan)
        resumed = len(diff.closed)
        attacked = attack(
            store,
            conducted,
            plan,
            diff,
            probes,
            resolver=resolver,
            target=target,
            attackers=attackers,
            started_at=started,
        )
        n_traces = _n_traces(store, run_id)
        manifest = write_manifest(
            store,
            run_id=run_id,
            spec_digest=versioned.digest(raw),
            probes_digest=report.probes_digest,
            dataset=attacked.dataset,
            profile=attacked.profile,
            exploit=attacked.exploit,
            n_total_traces=n_traces,
            # Coverage is the same difference that decided what to execute, read again now that the
            # attack closed: planned, closed and failed off the store's keys, never off a counter.
            coverage=difference(store, plan).coverage(),
            components={**_generation_provenance(report), **attacked.components},
        )
    except Exception as failed:
        # A crash anywhere in the attempt -- generation refused as much as the channel dying -- must
        # not leave the run reading its last phase forever, and it must not burn the run id either.
        # So the record goes under its own key, never `manifest.json`. The traces already written
        # stay, and the next launch resumes from the difference. The webhook fires either way, so
        # the consumer stops waiting.
        try:
            n_traces = _n_traces(store, run_id)
            _, failure_key = write_failure(
                store,
                run_id=run_id,
                attempt=attempt,
                error=failed,
                n_traces=n_traces,
                resumed=resumed,
            )
        except Exception as unrecorded:
            # The store is what is broken, and there is nowhere to write that down. The error that
            # ended the attempt is the one that surfaces, with this one chained behind it; a second
            # error about the store standing in for the first would send whoever reads the job's
            # log after the wrong thing.
            raise failed from unrecorded
        delivered = _notify(store, spec, RunPhase.FAILED, failure_key, webhook_client)
        return RunOutcome(run_id, RunPhase.FAILED, n_traces, resumed, failure_key, delivered)

    delivered = _notify(store, spec, RunPhase.COMPLETE, layout.manifest(run_id), webhook_client)
    return RunOutcome(
        run_id,
        RunPhase.COMPLETE,
        manifest.n_total_traces,
        resumed,
        layout.manifest(run_id),
        delivered,
    )


def _resolver(settings: Settings) -> SecretResolver:
    """How this run turns a `secret_ref` into a credential.

    The runner is the process that holds them: the target's key to reach the assistant, the judge's
    to reach its provider. The spec carries neither -- a frozen artifact with a live credential in
    it is a credential with an audit trail pointing at it.
    """
    return build_resolver(
        settings.secrets_backend.value,
        root=Path(settings.secrets_root) if settings.secrets_root else None,
    )


def _generate(
    store: ObjectStore,
    spec: RunSpec,
    settings: Settings,
    resolver: SecretResolver,
    knowledge_base: KnowledgeBase | None,
) -> GenerationReport:
    """The run's probe set: read back when `probes.json` pins it, generated in this process
    otherwise.

    `probes.json` is checked first, inside `generate_for`, and that is what pins the plan: a runner
    that generated on every launch would get a different set the day a catalogue was published
    between a crash and a relaunch -- content-derived ids, so different keys, so none of its traces
    found and the assistant attacked again. The brain is pulled by digest into a temporary
    directory and discarded with the generation.
    """
    request = GenerationRequest.from_spec(spec)
    registry = (
        brain_registry(settings, resolver)
        if spec.kb_ref is not None and knowledge_base is None
        else None
    )
    return generate_for(
        store,
        request,
        model=generator_for(spec.generator, resolver),
        registry=registry,
        knowledge_base=knowledge_base,
    )


def _generation_provenance(report: GenerationReport) -> dict[str, str]:
    """What generation said about itself, for the manifest's components: whether this attempt
    generated or found the set pinned, which half of the catalogues ran, which engines, and what
    was set aside or could not be built."""
    return {
        "generation": "pinned by an earlier attempt" if report.skipped_existing else "ran",
        "generation_grounded": str(report.grounded).lower(),
        "generation_engines": ",".join(report.engines_ran),
        "generation_set_aside": ",".join(report.strategies_set_aside),
        "generation_degenerate": ",".join(report.degenerate_strategies),
        "generation_unverified": str(len(report.unverified_probes)),
        "generation_contract_digest": report.contract_digest,
    }


def _n_traces(store: ObjectStore, run_id: str) -> int:
    """Closed conversations, counted off the store: the denominator every reader agrees on."""
    return sum(
        1 for k in store.list_prefix(layout.traces_prefix(run_id) + "/") if k.endswith(".zst")
    )


def _notify(
    store: ObjectStore,
    spec: RunSpec,
    phase: RunPhase,
    record: str,
    client: httpx.Client | None,
) -> Delivery:
    """Tell the consumer where to read, once per outcome, with the keys and never the content.

    The payload is a pointer: the record to read -- the manifest, or the failure record -- and the
    keys of the artifacts that exist. A consumer that misses it polls the status and reads the same
    thing, which is why delivery is bounded rather than guaranteed.
    """

    def _present(key: str) -> str | None:
        return key if store.exists(key) else None

    run_id = spec.run_id
    payload: dict[str, Any] = {
        "run_id": run_id,
        "phase": phase.value,
        "manifest": record,
        "artifacts": {
            "traces_prefix": layout.traces_prefix(run_id),
            "dataset": _present(layout.dataset(run_id)),
            "profile": _present(layout.profile(run_id)),
            "exploit": _present(layout.exploit(run_id)),
        },
    }
    return deliver(
        spec.webhook_url, payload, key=idempotency_key(run_id, phase.value), client=client
    )
