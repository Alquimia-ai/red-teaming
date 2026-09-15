"""Which construction a catalogue's key resolves to, and with what context.

**This is the seam the catalogue is data on one side of and code on the other.** A catalogue in the
store declares that a strategy uses `swap_token` or `contextual_sibling`; it carries no logic and
no vocabulary of ours. This module is what turns that string into a configured object: the
deterministic constructions close over the boundary the corpus attests, the model-driven ones close
over the run's declared context and the generator model. So a plugin and a strategy are not merely
YAML -- the key they name resolves to code, and that code is what ends up building the premise.

Two kinds of construction resolve here and they answer different questions:

* a `Transform` deforms an **entity** -- a name, a figure, a date -- and the engine that uses it
  reads a boundary, so what it produces can carry a defensible `doc = 0`;
* a `FactTwister` twists a **datum stated in a passage**, leaving the entity's name real. It needs
  no boundary and claims no absence, which is why gaussia keeps it off the transform registry
  entirely and lets its declared patterns become names a strategy may still call for. **None is
  registered yet** -- the second kind is the shape this registry is built to take, and the engine
  that reads passages is not composed until a run wires a model to twist with.

Keys are added, never replaced. gaussia refuses a key colliding with one of its four shipped
constructions, and this registry refuses a second builder under any name it already knows: two
builders behind one key means a probe set whose provenance names a construction and cannot say
which one ran.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from typing import Any

from gaussia.core.transform import Transform
from langchain_core.language_models.chat_models import BaseChatModel

from redteam_catalogue.contextual import CONTEXTUAL_SIBLING, ContextualSiblingTransform
from redteam_catalogue.transforms import (
    SHIFT_DATE,
    SHIFT_FIGURE,
    SWAP_TOKEN,
    ShiftDate,
    ShiftFigure,
    SwapAttestedToken,
)
from redteam_contracts.run_spec import ProbeContext


@dataclass(frozen=True)
class Ingredients:
    """Everything a construction may need, resolved before any of them is built.

    Passed whole rather than as separate arguments so adding a construction that needs something
    new does not change the signature every existing builder is written against.
    """

    boundary: frozenset[str]
    """Every entity of the kind this construction will be asked about."""

    context: ProbeContext | None = None
    """What the premises should sound like. `None` for a run that declared none, which is legal
    only while every key it names is deterministic."""

    model: BaseChatModel | None = None
    """The generator the run declared. `None` for the same reason."""

    kind: str = ""
    """Which entity kind this construction is being built for.

    Only the model-driven ones read it, and only to tell the model what it is naming: without it
    the prompt had to assume, and it assumed "product". Deterministic constructions read their rule
    off the datum's own shape and need no such telling.
    """


TransformBuilder = Callable[[Ingredients], Transform]


@dataclass(frozen=True)
class TransformDescriptor:
    key: str
    build: TransformBuilder
    needs_generator: bool = False
    needs_context: bool = False
    needs_brain: bool = True


class ContextRequired(ValueError):
    """A key needs the run's context or generator, and the spec declared neither.

    Refused at build time, before a probe exists. The alternative is a model asked to write Spanish
    premises with no language in front of it, which answers in the language of the prompt -- and
    the run then measures the assistant's handling of English questions about Spanish products.
    """

    def __init__(self, key: str, missing: str) -> None:
        super().__init__(
            f"the construction {key!r} needs the run's {missing}, and the spec declares none. "
            f"Either declare it or name a construction that reads its rule off the datum."
        )


_DESCRIPTORS: dict[str, TransformDescriptor] = {}


def register(
    key: str,
    build: TransformBuilder,
    *,
    needs_generator: bool = False,
    needs_context: bool = False,
    needs_brain: bool = True,
) -> None:
    """Bind a builder to the string a `StrategySpec.transform` may name.

    Registering the same builder twice is a no-op -- this is module state and the wiring is
    imported more than once per process. A *different* builder under a name already taken is
    refused, because that is the mistake worth catching.
    """
    declared = TransformDescriptor(
        key=key,
        build=build,
        needs_generator=needs_generator,
        needs_context=needs_context,
        needs_brain=needs_brain,
    )
    existing = _DESCRIPTORS.get(key)
    if existing is not None:
        if existing == declared:
            return
        raise ValueError(
            f"the construction key {key!r} already has a builder; exactly one per key, or a probe "
            f"set names a construction and cannot say which one produced it"
        )
    _DESCRIPTORS[key] = declared


def registered() -> tuple[str, ...]:
    """Every key a catalogue may name beyond gaussia's four."""
    return tuple(sorted(_DESCRIPTORS))


def descriptor(key: str) -> TransformDescriptor | None:
    return _DESCRIPTORS.get(key)


MODEL_DRIVEN: frozenset[str] = frozenset({CONTEXTUAL_SIBLING})
"""The keys whose construction writes premises with the run's generator, and so needs the run's
context and generator declared. Stated as data so the API's gate can refuse a run naming one of
them with neither, before anything is frozen, without building a construction -- which would cost a
request to the generator."""


def needs_model(key: str) -> bool:
    """Whether a construction key needs the run's generator and context to be built."""
    found = descriptor(key)
    return bool(found and found.needs_generator)


def build_transforms(keys: Iterable[str], ingredients: Ingredients) -> tuple[Transform, ...]:
    """The constructions this catalogue asked for, configured for this run.

    Args:
        keys: The `transform` values the catalogue names. Keys belonging to gaussia's shipped four
            are skipped: they need no configuration and gaussia resolves them itself.
        ingredients: The boundary, and the context and model where a construction needs them.

    Returns:
        The built constructions, in key order so a run is reproducible. **Pass this same sequence
        to `validate_catalogue` and to every engine**: a catalogue validated against one set and
        generated against another is where validation stops meaning anything.

    Raises:
        ContextRequired: A named construction needs context or a model the spec did not declare.
    """
    return tuple(
        _DESCRIPTORS[key].build(ingredients) for key in sorted(set(keys)) if key in _DESCRIPTORS
    )


def unresolved(transforms: Sequence[Transform]) -> dict[str, tuple[str, ...]]:
    """Per construction, the entities it could not deform into a defensible premise.

    Every construction here reports this, and it is the number worth reading before a run is
    trusted: an entity nothing could deform becomes a probe asking about something real under a
    strategy that declared it was asking about something invented.
    """
    reported: dict[str, tuple[str, ...]] = {}
    for transform in transforms:
        entities: frozenset[str] = getattr(transform, "unresolved", frozenset())
        if entities:
            reported[transform.key] = tuple(sorted(entities))
    return reported


class DeclaredKey(Transform):  # type: ignore[misc]  # gaussia ships no stubs
    """A construction named but not built, for the one question validation asks of it.

    Catalogue validation checks that every `StrategySpec.transform` resolves to something the run
    will have. It reads keys and nothing else -- so answering it does not require a model, a
    boundary, or a single request. Building the real construction to answer a question about its
    name would make publishing a catalogue cost what generating from it costs.

    `apply` refuses rather than returning the entity, because an entity returned unchanged is
    precisely how a strategy becomes a silent control, and this object must never reach generation.
    """

    def __init__(self, key: str) -> None:
        self._key = key

    @property
    def key(self) -> str:
        return self._key

    def apply(self, entity: str) -> str:
        raise NotImplementedError(
            f"{self._key!r} was declared for validation and never built; generation has to resolve "
            f"it through build_transforms with the run's boundary and context"
        )


def declared_transforms() -> tuple[Transform, ...]:
    """Every registered key, declared and unbuilt.

    What a catalogue is validated against at publish time, where the question is "could any
    installation run this" rather than "can this run". A run validates again against exactly the
    constructions it built.
    """
    return tuple(DeclaredKey(key) for key in registered())


def _swap_token(ingredients: Ingredients) -> Transform:
    return SwapAttestedToken(ingredients.boundary)


def _shift_figure(ingredients: Ingredients) -> Transform:
    return ShiftFigure(ingredients.boundary)


def _shift_date(ingredients: Ingredients) -> Transform:
    return ShiftDate(ingredients.boundary)


def _contextual_sibling(ingredients: Ingredients) -> Transform:
    if ingredients.context is None:
        raise ContextRequired(CONTEXTUAL_SIBLING, "context")
    if ingredients.model is None:
        raise ContextRequired(CONTEXTUAL_SIBLING, "generator model")
    built: Any = ContextualSiblingTransform(
        ingredients.model, ingredients.context, ingredients.boundary, kind=ingredients.kind
    )
    return built


register(SWAP_TOKEN, _swap_token)
register(SHIFT_FIGURE, _shift_figure)
register(SHIFT_DATE, _shift_date)
register(
    CONTEXTUAL_SIBLING,
    _contextual_sibling,
    needs_generator=True,
    needs_context=True,
)
