"""Probes, anchored in the knowledge base.

This is the only stage that sees the knowledge base; everything else depends on its interface.

Each probe carries its knowledge hook: `doc in {0, 1}`, and -- because our enumerator reads a brain
-- the block the entity came from. That is what makes every row of the result citable all the way to
its source without anyone having to take our word for it, and it is what separates this measurement
from most red teaming, which judges against another model's opinion.

The probe set is written **by digest** rather than to a deterministic path. Two runs over the same
knowledge base and the same catalogue produce the same set and store it once; the second skips the
write, not the generation, since the digest is of what was generated. Deduplicating traces would be
meaningless -- every conversation is unique by definition -- but two runs' provenance pointing at
one blob is still worth the digest.

**The library composes; this module only prepares and records.** Engine selection, the `doc` label,
the merge and the hook verdict are gaussia's, and none of it is re-implemented here. What is ours is
what the library cannot know: which construction each key resolves to, the boundary read once so
generation and validation see the same one, the block a probe cites, and the identity a probe keeps.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from gaussia.schemas.roastme import BehavioralContract, Catalogue, EngineDeclaration, Probe
from langchain_core.language_models.chat_models import BaseChatModel

from redteam_catalogue.documents import require_groundable, to_documents
from redteam_catalogue.engines import (
    boundaries,
    build_engines,
    build_library,
    build_verifier,
    transform_keys,
)
from redteam_catalogue.engines import entity_kinds as kinds_of
from redteam_catalogue.enumerator import BrainEntityEnumerator
from redteam_catalogue.premises import unresolved as unresolved_of
from redteam_catalogue.validate import validate
from redteam_contracts.kb import KnowledgeBase
from redteam_contracts.run_spec import ProbeContext

BLOCK_ID = "block_id"
GAUSSIA_PROBE_ID = "gaussia_probe_id"

_IDENTITY_CHARS = 32
"""Half a sha256, hex. The same width `attack_id` uses, for the same reason: long enough that a
collision is not a thing that happens, short enough to stay readable in a bucket listing."""


@dataclass(frozen=True)
class DegenerateStrategy:
    """A strategy that produced only documented premises, and so tested nothing it meant to.

    Named because gaussia warns about the case and it fails quietly otherwise: a construction that
    finds nothing to deform returns the entity unchanged, the engine correctly labels it documented,
    and the strategy becomes a second control while the catalogue still claims it attacks. Surfaced
    here rather than discovered in a coverage report that looks fine.
    """

    strategy_id: str
    transform: str
    declared_doc: int
    observed_doc: int


@dataclass(frozen=True)
class ProbeSet:
    probes: tuple[Probe, ...]
    digest: str
    declaration: EngineDeclaration
    degenerate: tuple[DegenerateStrategy, ...] = ()

    unresolved: dict[str, tuple[str, ...]] = field(default_factory=dict)
    """Per construction, the entities it could not deform into a defensible premise. Each one
    became a probe asking about something real under a strategy that declared otherwise."""

    unverified: tuple[str, ...] = ()
    """Probe ids whose `doc` label the verifier could not confirm. Not dropped: a smaller
    denominator that announces nothing is the failure the verification exists to catch."""

    @property
    def targeted_entities(self) -> frozenset[str]:
        return frozenset(p.hook.references for p in self.probes if p.hook is not None)


def generate(
    catalogue: Catalogue,
    kb: KnowledgeBase,
    *,
    contract: BehavioralContract | None = None,
    context: ProbeContext | None = None,
    model: BaseChatModel | None = None,
    name_like_kinds: Sequence[str] | None = None,
    grounded: bool = True,
) -> ProbeSet:
    """Build probes from the catalogue and the base.

    Args:
        catalogue: The plugins and strategies, as published. Data: it names constructions and never
            carries them.
        kb: The base. Read for its passages and for its boundary, and for nothing else.
        contract: The principles, so the catalogue's six semantic rejections can run before a single
            probe is generated. Skipped when absent, which is only sensible in a test.
        context: Language, domain and tone, for the constructions that need them.
        model: The generator the run declared, for the same.
        name_like_kinds: Which kinds the near-miss check applies to. Defaults to every kind the
            catalogue names, which is right for a base of names and wrong for one of statements --
            see `BrainHookVerifier`.
        grounded: Whether the run declared a knowledge base. `False` is a black-box run: the base
            is empty because there is none, the probes come back hookless and carry no `doc` label,
            and the strategies that lean on a premise are left out by the caller. It reaches
            `require_groundable` and `build_engines` because in both places an empty base means
            something different depending on whether one was asked for -- and taking it for granted
            is what made this path unreachable.

    Raises:
        UngroundableCorpus: A declared base cannot support the probes this catalogue asks for.
        ValueError: The catalogue fails one of the six rejections.
    """
    kinds = kinds_of(catalogue)
    passages = kb.documents(kinds)
    require_groundable(passages, needs_boundary=True, declared=grounded)
    documents = to_documents(passages)

    enumerator = BrainEntityEnumerator(kb)
    kind_boundaries = boundaries(enumerator, kinds, documents)

    engines, transforms = build_engines(
        catalogue, kb, kind_boundaries, context=context, model=model, grounded=grounded
    )
    if contract is not None:
        # Before generation, never after: a malformed catalogue should cost nothing, and certainly
        # not a conversation against the client. The same sequences reach both calls, because
        # validating against one set and generating against another is where validation stops
        # meaning anything.
        validate(catalogue, contract, list(engines), transforms)

    checked = kinds if name_like_kinds is None else name_like_kinds
    verifier = build_verifier(kb, catalogue, checked)
    library = build_library(engines, verifier)

    produced = [_cited(probe, enumerator) for probe in library.generate(documents, catalogue)]
    probes = tuple(sorted(produced, key=lambda probe: probe.id))

    return ProbeSet(
        probes=probes,
        digest=digest_of(probes),
        declaration=library.declaration,
        degenerate=_degenerate(catalogue, probes),
        unresolved=unresolved_of(transforms),
        unverified=tuple(
            probe.id for probe in probes if probe.hook is not None and probe.hook.verified is False
        ),
    )


def _cited(probe: Probe, enumerator: BrainEntityEnumerator) -> Probe:
    """The probe with a stable identity and the block it can be checked against.

    **The identity is re-keyed, and this is the load-bearing step.** gaussia numbers a probe by its
    position in the sorted boundary, which is right for a library whose probes live only as long as
    a run. Here the `attack_id` derives from `probe_id`, and the store answers "was this unit done"
    by whether that key exists -- so one entity added to the brain would shift every index after it,
    the resumed runner would find none of its keys, conclude nothing was done, and attack the
    assistant all over again. Nothing raises when that happens.

    So the identity is content: the engine, the strategy, the premise and how it was derived.
    **`engine` is in the digest on purpose.** gaussia scopes its ids by engine name so that probes
    two engines derived independently stay distinct -- collapsing them would merge a confirmed
    absence label with an unreliable one, and the absence guarantee would stop holding after
    composition.
    """
    hook = probe.hook
    meta: dict[str, Any] = {**probe.meta, GAUSSIA_PROBE_ID: probe.id}
    if hook is not None:
        block = enumerator.block_for(hook.kind, hook.base_entity or hook.references)
        if block:
            meta[BLOCK_ID] = block

    return probe.model_copy(update={"id": _identity(probe), "meta": meta})


def _identity(probe: Probe) -> str:
    hook = probe.hook
    payload = json.dumps(
        {
            "engine": probe.engine,
            "strategy": probe.strategy,
            "references": hook.references if hook else None,
            "how": hook.how if hook else None,
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:_IDENTITY_CHARS]


def _degenerate(catalogue: Catalogue, probes: Sequence[Probe]) -> tuple[DegenerateStrategy, ...]:
    """Strategies that declared they would attack and produced only documented premises.

    Read off the hooks rather than off the constructions, so it catches every route to the same
    outcome: a transform with nothing to deform, a model that resolved nothing, and a premise that
    happened to name something real.
    """
    observed: dict[str, set[int]] = {}
    for probe in probes:
        if probe.hook is not None:
            observed.setdefault(probe.strategy, set()).add(probe.hook.doc)

    return tuple(
        DegenerateStrategy(
            strategy_id=strategy.id,
            transform=strategy.transform,
            declared_doc=strategy.doc,
            observed_doc=1,
        )
        for strategy in catalogue.strategies
        if strategy.doc == 0 and observed.get(strategy.id) == {1}
    )


def digest_of(probes: Sequence[Probe]) -> str:
    """Content address for the whole set, so an identical set is recognised as identical.

    Public, and the **only** definition of a probe set's identity. A second definition -- a job
    hashing its own serialisation of the same probes -- would give one artifact two digests, with
    the blob stored under the one that was not `ProbeSet.digest`; whichever a reader had, it could
    not be checked against the other.

    Over the probes rather than over any rendering of them, and sorted by id, so the digest is a
    property of the set: the same probes from catalogues named in a different order are the same
    set, and answer with the same address.
    """
    payload = json.dumps(
        [p.model_dump(mode="json") for p in sorted(probes, key=lambda p: p.id)],
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode()).hexdigest()


__all__ = ["DegenerateStrategy", "ProbeSet", "digest_of", "generate", "transform_keys"]
