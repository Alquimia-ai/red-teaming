"""Wiring. The one place that knows which backend is in play.

Everything the settings choose is resolved here and nowhere else, so the rest of the API is written
against interfaces and the platform stays confined to the three seams: where evidence is stored, how
a runner is launched, where secrets are read from.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from redteam_catalogue import assets
from redteam_catalogue.premises import needs_model
from redteam_contracts.contract import ContractSpec
from redteam_contracts.run_spec import RunSpec
from redteam_dispatch import Dispatcher, build_dispatcher
from redteam_secrets.resolver import SecretResolver, build_resolver
from redteam_settings.config import DispatchBackend, SecretsBackend, Settings, load
from redteam_store import contract as contract_store
from redteam_store import delivery, grounding, layout
from redteam_store.backends import build_store
from redteam_store.interface import ObjectNotFound, ObjectStore


@lru_cache(maxsize=1)
def settings() -> Settings:
    return load()


@lru_cache(maxsize=1)
def store() -> ObjectStore:
    """The store this deployment asked for, verified before the first spec is frozen."""
    return build_store(settings().store_backend.value, settings())


@lru_cache(maxsize=1)
def resolver() -> SecretResolver:
    """How a `secret_ref` becomes a credential in this deployment."""
    configured = settings()
    return build_resolver(
        configured.secrets_backend.value,
        root=Path(configured.secrets_root) if configured.secrets_root else None,
    )


def runner_env(configured: Settings) -> dict[str, str]:
    """What every runner this API launches gets in its environment: the same store, seen from the
    other side. A runner pointed at a different store would resume against nothing.

    Always `env` for the runner's own secrets backend, whatever backend the API resolves through:
    the values a launch hands over -- resolved by the API, or referenced into a Job -- land as
    environment variables. Forwarding a `file` backend would point the runner at a directory nothing
    mounts into its container.

    The store's own credentials travel inline for a runner on this host or this daemon, which is
    where the API's values are the runner's values too. On a cluster they do not: the runner's pod
    reads them from the Secret the deployment mounts, and the API never writes a credential into a
    Job's spec.
    """
    wiring = {
        "REDTEAM_STORE_BACKEND": configured.store_backend.value,
        "REDTEAM_S3_BUCKET": configured.s3_bucket,
        "REDTEAM_SECRETS_BACKEND": SecretsBackend.ENV.value,
        "REDTEAM_BRAIN_REGISTRY_INSECURE": str(configured.brain_registry_insecure).lower(),
    }
    optional = {
        "REDTEAM_S3_ENDPOINT": configured.s3_endpoint,
        "REDTEAM_S3_REGION": configured.s3_region,
        "REDTEAM_BRAIN_REGISTRY_SECRET_REF": configured.brain_registry_secret_ref,
    }
    if configured.dispatch_backend is not DispatchBackend.K8S_JOB:
        optional["REDTEAM_S3_ACCESS_KEY"] = configured.s3_access_key
        optional["REDTEAM_S3_SECRET_KEY"] = configured.s3_secret_key
    wiring.update({key: value for key, value in optional.items() if value})
    return wiring


@lru_cache(maxsize=1)
def dispatcher() -> Dispatcher:
    configured = settings()
    return build_dispatcher(
        configured.dispatch_backend.value,
        configured,
        resolver=resolver(),
        env=runner_env(configured),
    )


def hands_values() -> bool:
    """Whether the dispatcher this deployment uses resolves a run's secrets itself.

    The docker and subprocess backends hand the runner values, so a reference nothing resolves has
    to be refused here, before the spec is frozen. The kubernetes backend hands references into the
    platform's Secret, which this process may not hold -- and refusing a run for a key the cluster
    has would be wrong.
    """
    return settings().dispatch_backend is not DispatchBackend.K8S_JOB


def secret_refs_for(spec: RunSpec) -> tuple[str, ...]:
    """Every reference the runner will resolve, and nothing another run's would.

    The spec's own -- the connector's, the judge's, the generator's, the embedder's, every
    attacker's -- and the platform's one reference the runner needs beyond them: the brain
    registry's credential, when the deployment names one **and the run declares a knowledge base**.
    A run with no brain pulls nothing, and asking it to carry a registry credential would refuse
    every brainless run on a deployment whose registry needs one. Forwarding exactly those is least
    privilege by construction.
    """
    models = (spec.judge, spec.generator, spec.embedder, *spec.attackers.values())
    named = [spec.connector.secret_ref, *(m.secret_ref for m in models if m is not None)]
    registry = settings().brain_registry_secret_ref
    if registry and spec.kb_ref is not None:
        named.append(registry)
    return tuple(dict.fromkeys(ref for ref in named if ref))


def catalogue_versions() -> dict[str, int]:
    """Every published catalogue and its newest version, read off one listing of the store."""
    newest: dict[str, int] = {}
    for key in store().list_prefix(layout.catalogues_prefix() + "/"):
        parsed = layout.parse_catalogue_key(key)
        if parsed is not None:
            name, version = parsed
            newest[name] = max(version, newest.get(name, 0))
    return newest


def attackers_named(spec: RunSpec, versions: Mapping[str, int]) -> frozenset[str]:
    """The attacker ids the strategies this run will generate are delivered through, at the
    versions the run is frozen with and under the run's own shape and selectors.

    Raises:
        ValueError: Two of the run's catalogues deliver one strategy id differently.
    """
    return delivery.attackers_named(
        store(),
        versions,
        grounded=spec.kb_ref is not None,
        plugins=spec.plugins,
        strategies=spec.strategies,
    )


def shared_contract(versions: Mapping[str, int]) -> tuple[ContractSpec, str]:
    """The one contract every catalogue the run names carries, and its digest.

    Raises:
        ContractMismatch: The catalogues disagree.
        ContractMissing: A published version carries none, which is a store somebody edited.
    """
    return contract_store.shared(store(), versions)


@dataclass(frozen=True)
class Selection:
    """What the run will actually generate from, at the versions it froze: the strategies that
    survive the run's selectors and its shape, and the construction keys they name."""

    strategies: frozenset[str]
    transform_keys: frozenset[str]

    @property
    def model_driven(self) -> frozenset[str]:
        return frozenset(key for key in self.transform_keys if needs_model(key))


def effective_selection(spec: RunSpec, versions: Mapping[str, int]) -> Selection:
    """The half of each catalogue this run generates from, narrowed to what it asked for.

    The same two rules generation applies -- `narrow` keeps what the selectors name and every
    control; `generatable` keeps the half that matches the run's shape -- run here over the frozen
    versions, so a run that would generate nothing is refused before anything is written.

    Raises:
        assets.EmptySelection: The selectors leave nothing that attacks.
        assets.NothingToGenerate: A catalogue has no strategy written for this run's shape.
    """
    grounded = spec.kb_ref is not None
    strategies: set[str] = set()
    keys: set[str] = set()
    for name, version in versions.items():
        catalogue = assets.load(store(), name, version)
        selected = assets.narrow(catalogue, spec.plugins, spec.strategies)
        usable = assets.generatable(
            selected,
            grounded=grounded,
            declared=grounding.load(store(), name, version),
            name=name,
        )
        for strategy in usable.strategies:
            strategies.add(strategy.id)
            keys.add(strategy.transform)
    return Selection(strategies=frozenset(strategies), transform_keys=frozenset(keys))


def planned_units(run_id: str) -> int | None:
    """How many units the run intends, or None while that is not yet knowable.

    The count is probes x replicas, and the probe count only exists once generation has closed --
    it is written into `probes.json` at that moment. Before then the honest answer is "not yet
    known": reporting 0 planned beside 16 closed is a number that contradicts the run it describes.
    """
    spec = RunSpec.model_validate_json(store().get(layout.spec(run_id)))
    try:
        probes = json.loads(store().get(layout.probes(run_id)))
    except ObjectNotFound:
        return None
    return int(probes["count"]) * spec.replicas
