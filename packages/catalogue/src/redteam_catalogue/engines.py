"""Composing the probe engines this run's catalogue asks for.

`ProbeLibrary` composes rather than cascades: every engine that can handle a passage sees it, and
every engine's output contributes to one merged set, each probe still recording which engine
produced it.

**Only the enumeration engine is composed today.** The structure is the library's and takes more,
but this builds one, so a run's `EngineDeclaration` names one and the absence/breadth trade-off has
nothing to trade against yet. Said here because the composition is what the file is about, and a
module that describes what its shape allows reads exactly like one describing what it does.

**One engine per entity kind, and that is not an optimisation.** A construction closes over the
boundary it will deform -- `swap_token` recombines tokens the corpus attests for *that kind* -- and
an engine takes one transform sequence for every kind it handles. Handing a single engine the
transforms of several kinds means a strategy over values building its premises out of product
names, which is exactly the confusion gaussia warns about in its own `_handles`: the shipped graph
and multi-hop engines ignore the kind argument and hand the same boundary to every strategy.
Declaring one engine per kind uses the mechanism gaussia already has instead of working around it.

**What is missing, and what it waits on.** `GroundedProbeEngine` needs no boundary at all -- it
twists a datum a passage states and leaves the entity's name real, so nothing it emits claims an
absence. It is the natural second engine and it is not here, because it twists through a model and
no run has wired one yet. It joins once, for every kind, the moment one does.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from gaussia.core.hook_verifier import HookVerifier
from gaussia.core.probe_engine import ProbeEngine
from gaussia.core.transform import Transform
from gaussia.generators.roastme.probes.enumeration import EnumerationProbeEngine
from gaussia.generators.roastme.probes.library import ProbeLibrary
from gaussia.schemas.roastme import Catalogue
from langchain_core.language_models.chat_models import BaseChatModel

from redteam_catalogue.enumerator import BrainEntityEnumerator
from redteam_catalogue.premises import Ingredients, build_transforms
from redteam_catalogue.verifier import BrainHookVerifier
from redteam_contracts.kb import KnowledgeBase
from redteam_contracts.run_spec import ProbeContext

ENUMERATION = "enumeration"


def entity_kinds(catalogue: Catalogue) -> tuple[str, ...]:
    """The kinds this catalogue names, in a stable order."""
    return tuple(sorted({strategy.entity_kind for strategy in catalogue.strategies}))


def transform_keys(catalogue: Catalogue, kind: str | None = None) -> tuple[str, ...]:
    """The constructions this catalogue names, in a stable order.

    Narrowed to one kind when asked, because a construction closes over the boundary it will
    deform. Building every key for every kind is not merely wasted work: a figure construction
    handed a boundary of product names reports every one of them as something it could not deform,
    and that noise is indistinguishable from the real finding the report exists to carry.
    """
    return tuple(
        sorted(
            {
                strategy.transform
                for strategy in catalogue.strategies
                if kind is None or strategy.entity_kind == kind
            }
        )
    )


def boundaries(
    enumerator: BrainEntityEnumerator, kinds: Sequence[str], documents: list[Any]
) -> dict[str, frozenset[str]]:
    """What the base holds for each kind, read once and reused.

    Read once because generation and validation must both see the same boundary: a construction
    built against one view and a label derived from another is how a `doc` label stops meaning
    anything. gaussia exposes `ParticularisingEngine.boundary` for the same reason -- the written
    advice for any new corpus is to print it before spending a run on it, and a prescribed step the
    API does not support is a step that gets skipped.
    """
    return {kind: enumerator.enumerate_entities(kind, documents) for kind in kinds}


def build_engines(
    catalogue: Catalogue,
    kb: KnowledgeBase,
    kind_boundaries: Mapping[str, frozenset[str]],
    *,
    context: ProbeContext | None = None,
    model: BaseChatModel | None = None,
    grounded: bool = True,
) -> tuple[tuple[ProbeEngine, ...], tuple[Transform, ...]]:
    """The engines and the constructions they were built with.

    Both are returned because both have to reach `validate_catalogue` unchanged. gaussia is explicit
    that passing a different sequence to validation than to generation is where a catalogue that
    validated can still fail at generation -- so they leave here together and travel together.

    Args:
        grounded: Whether this run declared a knowledge base at all. It decides what an empty
            boundary *means*, and that is the whole reason it has to be passed rather than
            inferred from the boundaries: for a run that named a base, an empty boundary is a kind
            the base does not carry -- a typo, most likely -- and no engine may declare it. For a
            run that named none, every boundary is empty and that says nothing about any kind, so
            refusing to declare them would refuse the catalogue for the one reason that is not the
            catalogue's fault. gaussia's own no-corpus path makes the same distinction and states
            it: "an engine's declaration is a claim about what it is competent for, and nothing
            about that claim depends on a corpus being there to read."
    """
    enumerator = BrainEntityEnumerator(kb)
    engines: list[ProbeEngine] = []
    every_transform: list[Transform] = []

    for kind in entity_kinds(catalogue):
        boundary = kind_boundaries.get(kind, frozenset())
        transforms = build_transforms(
            transform_keys(catalogue, kind),
            Ingredients(boundary=boundary, context=context, model=model, kind=kind),
        )
        # Built for every kind, including one the base carries nothing for. Validation checks that
        # each construction a catalogue names resolves, and dropping the ones belonging to an
        # absent kind would report a typo as an unknown construction -- pointing at the wrong half
        # of the mistake. Over an empty boundary each of them resolves nothing and costs nothing,
        # the model-driven one included: it has no entity to ask about.
        every_transform.extend(transforms)

        # The engine, though, only for a kind the base actually carries -- when there is a base.
        # That is what keeps the sixth rejection meaningful for a grounded run: it asks whether
        # some configured engine can produce a kind, and an engine declaring whatever it was
        # handed answers yes to a typo. What the base holds is a fact, so `policyy` finds an empty
        # boundary, is never declared, and the catalogue is refused by name before a single probe
        # is generated.
        #
        # A run that declared no base is the case that distinction cannot serve: every boundary is
        # empty, so refusing to declare any kind would refuse every catalogue for the one reason
        # that is not the catalogue's fault, and it is what made gaussia's no-corpus path
        # unreachable from here. The kinds are declared as the catalogue names them, exactly as
        # publish-time validation does for the same reason, and the probes come back hookless.
        if boundary or not grounded:
            engines.append(EnumerationProbeEngine(enumerator, [kind], transforms))

    return tuple(engines), tuple(every_transform)


def build_verifier(
    kb: KnowledgeBase, catalogue: Catalogue, name_like_kinds: Sequence[str]
) -> HookVerifier:
    """The independent check on every hook's label."""
    return BrainHookVerifier(kb, BrainEntityEnumerator(kb), name_like_kinds)


def build_library(engines: Sequence[ProbeEngine], verifier: HookVerifier | None) -> ProbeLibrary:
    """The composed library. Nothing here decides what a probe means -- the engines do."""
    return ProbeLibrary(engines, verifier)


def declared_engines(kinds: Sequence[str] = ()) -> tuple[list[ProbeEngine], tuple[Transform, ...]]:
    """The engines and constructions a catalogue is validated against at publish time.

    Five of the six rejections are decidable from the catalogue and the contract alone, and they
    are the ones worth running here: a duplicate identifier, a dangling principle, a dangling
    plugin and an unknown construction are all wrong whoever runs the catalogue.

    **The sixth is not decidable here and is not pretended to be.** It asks whether a configured
    engine can produce each entity kind, and what a given installation can enumerate is a fact
    about a knowledge base the publisher has not been given. So the kinds are declared as the
    catalogue names them, which makes the check pass by construction -- and the run performs it for
    real, against the kinds its own base turned out to carry.
    """
    from redteam_catalogue.memory_kb import MemoryKnowledgeBase
    from redteam_catalogue.premises import declared_transforms

    enumerator = BrainEntityEnumerator(MemoryKnowledgeBase([]))
    transforms = declared_transforms()
    engine: ProbeEngine = EnumerationProbeEngine(enumerator, list(kinds), transforms)
    return [engine], transforms
