"""Generating a run's probe set: the work, apart from the process that runs it.

Nothing here knows about the store's layout or decides *whether* to generate -- it generates what it
is given, against the base the run declared, and reports what it could not build.
"""

from __future__ import annotations

from dataclasses import dataclass

from gaussia.schemas.roastme import Probe
from langchain_core.language_models.chat_models import BaseChatModel

from redteam_catalogue import assets
from redteam_catalogue.memory_kb import MemoryKnowledgeBase
from redteam_contracts.kb import KnowledgeBase
from redteam_probes.generate import digest_of, generate
from redteam_probes.request import GenerationRequest
from redteam_store.interface import ObjectStore


@dataclass(frozen=True)
class Generated:
    """Every catalogue's probes and every catalogue's findings, merged."""

    probes: list[Probe]
    digest: str
    """The set's content address, from `generate.digest_of` -- the same function that computes
    `ProbeSet.digest`, over the merged probes. Carried rather than recomputed downstream."""

    catalogue_versions: dict[str, int]
    contract_digest: str
    degenerate: tuple[str, ...]
    engines: tuple[str, ...]
    unresolved: dict[str, tuple[str, ...]]
    unverified: tuple[str, ...]
    grounded: bool = True
    set_aside: tuple[str, ...] = ()


def resolve_versions(store: ObjectStore, request: GenerationRequest) -> dict[str, int]:
    """The version of every catalogue the run named: the one it froze, or the newest for a spec
    nobody accepted."""
    return {
        name: request.catalogue_versions.get(name) or assets.latest(store, name)
        for name in request.catalogues
    }


def generate_all(
    store: ObjectStore,
    request: GenerationRequest,
    kb: KnowledgeBase,
    *,
    model: BaseChatModel | None = None,
) -> Generated:
    """Generate from every catalogue the run named, against the base the run declared.

    **Each run generates the half of its catalogues written for its own shape**, and `grounded` on
    the result says which half that was. A strategy whose phrasing carries `{premise}` needs a base
    to draw one from; one that stands without a premise must not be handed one, because gaussia
    appends it. `generatable` splits them and what it leaves out is reported rather than dropped in
    silence.

    The contract every selected catalogue carries is resolved once and shared: a run over several
    catalogues that disagree on the contract is refused here with `ContractMismatch`, and the
    catalogue of each is validated against that one contract before a probe exists.
    """
    brain_declared = request.brain is not None
    versions = resolve_versions(store, request)
    contract_spec, contract_digest = assets.shared_contract(store, versions)
    from redteam_catalogue.contract import validation_contract

    contract = validation_contract(contract_spec)
    language = request.context.language if request.context is not None else "und"

    probes: list[Probe] = []
    degenerate: list[str] = []
    engines: list[str] = []
    unresolved: dict[str, list[str]] = {}
    unverified: list[str] = []
    left_out: list[str] = []

    for name, version in versions.items():
        document = assets.selected_document(
            assets.load_document(store, name, version), request.plugins, request.strategies
        )
        required = tuple(s for s in document.strategies if s.requires_brain)
        independent = tuple(s for s in document.strategies if not s.requires_brain)
        if required and not brain_declared:
            raise ValueError(
                f"the selected strategies {sorted(s.id for s in required)} require a brain, and "
                "this run declares none"
            )
        for strategies, base, uses_brain in (
            (required, kb, True),
            (independent, no_base(), False),
        ):
            if not strategies:
                continue
            sliced = document.model_copy(update={"strategies": strategies})
            catalogue = assets.as_catalogue(sliced, language)
            produced = generate(
                catalogue,
                base,
                contract=contract,
                context=request.context,
                model=model,
                grounded=uses_brain,
                strategies={strategy.id: strategy for strategy in strategies},
                language=language,
            )
            probes.extend(produced.probes)
            degenerate.extend(d.strategy_id for d in produced.degenerate)
            engines.extend(produced.declaration.ran)
            for construction, entities in produced.unresolved.items():
                unresolved.setdefault(construction, []).extend(entities)
            unverified.extend(produced.unverified)

    # Sorted, so the artifact is canonical: the same probes from catalogues named in a different
    # order serialise to the same bytes under the same digest.
    probes.sort(key=lambda probe: probe.id)

    return Generated(
        probes=probes,
        digest=digest_of(probes),
        catalogue_versions=versions,
        contract_digest=contract_digest,
        degenerate=tuple(dict.fromkeys(degenerate)),
        engines=tuple(dict.fromkeys(engines)),
        unresolved={
            construction: tuple(dict.fromkeys(entities))
            for construction, entities in unresolved.items()
        },
        unverified=tuple(unverified),
        grounded=any(
            strategy.requires_brain
            for name, version in versions.items()
            for strategy in assets.selected_document(
                assets.load_document(store, name, version), request.plugins, request.strategies
            ).strategies
        ),
        set_aside=tuple(dict.fromkeys(left_out)),
    )


def no_base() -> KnowledgeBase:
    """The base a run that declared none generates from: an empty one.

    Not a stand-in and not a fixture: an invented corpus with fabricated block ids would flow into
    `Probe.meta["block_id"]` and every "citable to its source" claim would point at a string this
    package made up. The catalogue's own strategies say which of them can run without a base; the
    ones that cannot are set aside and reported.
    """
    return MemoryKnowledgeBase([])
