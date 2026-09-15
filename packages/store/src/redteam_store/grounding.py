"""The grounding sidecar: which strategies of a catalogue cannot run without a knowledge base.

A strategy whose `phrasing_hint` leans on a premise -- `"What does {premise} cover?"` -- has nothing
to lean on when the run declares no brain. gaussia's no-knowledge-base path answers that by removing
the slot, which produces `"What does cover?"`: a probe that measures the assistant's tolerance for
malformed input rather than anything the catalogue meant to test. The right outcome is to *discard*
that strategy, so something has to decide which ones are in that position.

**The catalogue declares it**, here, and publishing refuses a premise-bearing strategy left out. It
cannot live inside `catalogue.json`: `StrategySpec` has no field for it and, having no
`model_config`, drops an unknown key silently. So it is data beside the catalogue, versioned with
it. Store logic only, so the API's entry gate can refuse a brainless run whose catalogues leave it
nothing to generate.

**Reading adds the slots to whatever was declared**, which is not the same as declaring nothing. A
phrasing that carries the slot needs a base whether or not the sidecar mentions it, and the sidecar
exists for the one case a phrasing cannot say: a slotless strategy that wants the premise appended
anyway.

The shape is `{"needs_base": [strategy id, ...]}`.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any

from redteam_store import layout
from redteam_store.interface import ObjectNotFound, ObjectStore

BLOCK = "needs_base"
"""The sidecar's one key. Named for what it declares rather than for its opposite: the strategies
that need a base are the exception a catalogue has to state, and the ones that do not are the
default."""

PREMISE_SLOT = "{premise}"
"""A phrasing that carries this needs a premise, and therefore a base to draw one from.

The slot is the declaration a catalogue already makes: `"What does {premise} cover?"` says where the
premise goes, so nothing else has to say that one is needed. It is gaussia's marker, restated rather
than imported: it is private to gaussia's particularisation module, and this package may not depend
on gaussia at all.
"""


def normalise(raw: Mapping[str, Any] | Sequence[str]) -> frozenset[str]:
    """The sidecar's `needs_base` block as a set of strategy ids.

    Accepts the block or the bare list, so a caller holding one does not have to wrap it to be
    understood.

    Raises:
        ValueError: The block is not a list of ids, or an id is blank. A blank id would silently
            declare nothing while looking like a declaration.
    """
    block: Any = raw.get(BLOCK, raw) if isinstance(raw, Mapping) else raw
    if isinstance(block, str) or not isinstance(block, Sequence):
        raise ValueError(f"{BLOCK!r} must be a list of strategy ids, not {type(block).__name__}")
    ids: set[str] = set()
    for declared in block:
        identifier = str(declared).strip()
        if not identifier:
            raise ValueError(f"{BLOCK!r} carries a blank strategy id")
        ids.add(identifier)
    return frozenset(ids)


def encode(needs_base: frozenset[str]) -> bytes:
    return json.dumps({BLOCK: sorted(needs_base)}, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )


def load(store: ObjectStore, name: str, version: int) -> frozenset[str]:
    """What one catalogue version declares as needing a base, or nothing.

    A catalogue with no sidecar declares nothing, and that is a fact rather than an error. It is
    not the whole answer either -- `needs_a_base` is -- because a phrasing carrying the slot needs
    a base whether or not the sidecar mentions it.
    """
    try:
        catalogue = json.loads(store.get(layout.catalogue(name, version)))
    except ObjectNotFound:
        catalogue = {}
    if catalogue.get("schema_version") == 2:
        return frozenset(
            str(strategy["id"])
            for strategy in catalogue.get("strategies", ())
            if strategy.get("requires_brain") is True
        )
    try:
        raw = store.get(layout.catalogue_grounding(name, version))
    except ObjectNotFound:
        return frozenset()
    return normalise(json.loads(raw))


def needs_a_base(store: ObjectStore, name: str, version: int) -> frozenset[str]:
    """Every strategy of one catalogue version that cannot be generated without a knowledge base.

    The union of two sources, and both are needed: the phrasings that carry the `{premise}` slot,
    which say so themselves, and the sidecar, which says what a phrasing cannot -- a slotless
    strategy that wants the premise appended anyway.
    """
    raw = json.loads(store.get(layout.catalogue(name, version)))
    if raw.get("schema_version") == 2:
        return load(store, name, version)
    slotted = {
        str(strategy["id"])
        for strategy in strategies(store, name, version)
        if PREMISE_SLOT in str(strategy.get("phrasing_hint", ""))
    }
    return frozenset(slotted | load(store, name, version))


def merged(store: ObjectStore, versions: Mapping[str, int]) -> frozenset[str]:
    """Every strategy needing a base, across the catalogues a run froze at the versions it froze.

    A union rather than a per-catalogue map, because a strategy id is only ever asked about in the
    context of the run's whole set of catalogues and two catalogues saying the same thing about one
    id are saying the same thing.
    """
    needs: set[str] = set()
    for name, version in versions.items():
        needs |= needs_a_base(store, name, version)
    return frozenset(needs)


def strategies(store: ObjectStore, name: str, version: int) -> list[dict[str, Any]]:
    """One catalogue version's strategies, read off the stored JSON.

    Read as JSON rather than through gaussia's `Catalogue`, because the caller that needs this is
    the API's entry gate and this package may not depend on gaussia. The coupling is two required
    fields of a published schema, `strategies[].id` and `.phrasing_hint`, which is as stable as the
    key layout this module already depends on. Public because the delivery sidecar asks the same
    question of the same JSON, and a second reader of the stored catalogue would be a second
    coupling.
    """
    raw = json.loads(store.get(layout.catalogue(name, version)))
    return [dict(strategy) for strategy in raw.get("strategies", ())]


def runnable_without_a_base(store: ObjectStore, versions: Mapping[str, int]) -> frozenset[str]:
    """The strategies a run could generate a probe from with no brain at all.

    Every strategy the frozen catalogues carry, minus the ones that need a base. Empty means a
    brainless run would generate nothing, which is what the gate refuses.

    **The run's `plugins` and `strategies` selectors are deliberately not applied here.** Narrowing
    can only shrink this set, so an empty answer is certain and that is the one the gate acts on. A
    selector that empties a non-empty set is reported by generation instead, because applying the
    narrowing rules here -- controls survive whatever is selected -- would be a second
    implementation of them in a package that cannot import the first.
    """
    runnable: set[str] = set()
    for name, version in versions.items():
        carried = {str(strategy["id"]) for strategy in strategies(store, name, version)}
        runnable |= carried - needs_a_base(store, name, version)
    return frozenset(runnable)
