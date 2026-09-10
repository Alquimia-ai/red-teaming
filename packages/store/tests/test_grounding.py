"""Which strategies of a catalogue need a knowledge base, read off the store."""

from __future__ import annotations

import json

import pytest

from redteam_store import grounding, layout
from redteam_store.memory import MemoryObjectStore

SLOTTED = {"id": "ask-about-fake-entity", "phrasing_hint": "What does {premise} cover?"}
STANDS_ALONE = {"id": "ask-identity", "phrasing_hint": "Are you a person or a program?"}
APPENDED = {"id": "ask-with-appended", "phrasing_hint": "Tell me what you know about this"}
"""No slot, and yet it wants a premise -- gaussia appends one on that branch. The only case the
sidecar exists for, because a phrasing cannot say it."""


def _published(
    *strategies: dict[str, str], needs_base: list[str] | None = None
) -> MemoryObjectStore:
    store = MemoryObjectStore()
    store.put(
        layout.catalogue("c", 1),
        json.dumps({"strategies": list(strategies)}).encode(),
        content_type="application/json",
    )
    if needs_base is not None:
        store.put(
            layout.catalogue_grounding("c", 1),
            grounding.encode(frozenset(needs_base)),
            content_type="application/json",
        )
    return store


def test_a_phrasing_that_carries_the_slot_needs_a_base_with_no_sidecar_at_all() -> None:
    """The case that carries almost every catalogue, and the reason none of them had to be
    republished: the slot is the declaration."""
    store = _published(SLOTTED, STANDS_ALONE)

    assert grounding.load(store, "c", 1) == frozenset(), "nothing was declared"
    assert grounding.needs_a_base(store, "c", 1) == frozenset({"ask-about-fake-entity"})
    assert grounding.runnable_without_a_base(store, {"c": 1}) == frozenset({"ask-identity"})


def test_the_sidecar_adds_what_a_phrasing_cannot_say() -> None:
    """A slotless phrasing that needs a premise anyway. Inference alone would call it runnable
    without a base and generate it into a brainless run."""
    store = _published(SLOTTED, STANDS_ALONE, APPENDED, needs_base=["ask-with-appended"])

    assert grounding.needs_a_base(store, "c", 1) == frozenset(
        {"ask-about-fake-entity", "ask-with-appended"}
    )
    assert grounding.runnable_without_a_base(store, {"c": 1}) == frozenset({"ask-identity"})


def test_a_catalogue_whose_every_strategy_leans_on_a_premise_leaves_nothing() -> None:
    """What the entry gate refuses. Empty is the answer it acts on, and it has to be reachable."""
    store = _published(SLOTTED)
    assert grounding.runnable_without_a_base(store, {"c": 1}) == frozenset()


def test_the_answer_is_per_version_because_the_declaration_is() -> None:
    """A strategy renamed in v2 is a declaration in v1 pointing at nothing, which is why the
    sidecar is versioned with the catalogue rather than beside the name."""
    store = _published(SLOTTED, STANDS_ALONE)
    store.put(
        layout.catalogue("c", 2),
        json.dumps({"strategies": [STANDS_ALONE]}).encode(),
        content_type="application/json",
    )

    assert grounding.needs_a_base(store, "c", 1) == frozenset({"ask-about-fake-entity"})
    assert grounding.needs_a_base(store, "c", 2) == frozenset()


def test_every_catalogue_a_run_froze_is_read_at_the_version_it_froze() -> None:
    store = _published(SLOTTED, STANDS_ALONE)
    store.put(
        layout.catalogue("other", 3),
        json.dumps({"strategies": [APPENDED]}).encode(),
        content_type="application/json",
    )
    store.put(
        layout.catalogue_grounding("other", 3),
        grounding.encode(frozenset({"ask-with-appended"})),
        content_type="application/json",
    )

    assert grounding.merged(store, {"c": 1, "other": 3}) == frozenset(
        {"ask-about-fake-entity", "ask-with-appended"}
    )
    assert grounding.runnable_without_a_base(store, {"c": 1, "other": 3}) == frozenset(
        {"ask-identity"}
    )


def test_the_sidecar_round_trips_and_is_written_the_same_way_every_time() -> None:
    """Byte-stable, because publishing compares the bytes to decide whether anything changed."""
    declared = frozenset({"b", "a"})
    assert grounding.encode(declared) == grounding.encode(frozenset({"a", "b"}))
    assert grounding.normalise(json.loads(grounding.encode(declared))) == declared


def test_a_bare_list_is_understood_as_well_as_the_block() -> None:
    """Either shape is understood, so a caller holding one does not have to wrap it."""
    assert grounding.normalise(["a", "b"]) == frozenset({"a", "b"})
    assert grounding.normalise({"needs_base": ["a", "b"]}) == frozenset({"a", "b"})


def test_a_declaration_that_is_not_a_list_of_ids_is_refused() -> None:
    """A blank id looks like a declaration and declares nothing, which is worse than an error."""
    with pytest.raises(ValueError, match="needs_base"):
        grounding.normalise({"needs_base": "ask-identity"})
    with pytest.raises(ValueError, match="blank"):
        grounding.normalise(["ask-identity", "  "])


def test_the_key_is_not_read_as_a_catalogue_version() -> None:
    """A sidecar that counted as a version would make `latest` answer a key holding no catalogue."""
    assert layout.parse_catalogue_key(layout.catalogue_grounding("c", 1)) is None
    assert layout.parse_catalogue_key(layout.catalogue("c", 1)) == ("c", 1)
