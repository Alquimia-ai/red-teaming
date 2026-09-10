"""The delivery sidecar: read back by the version a run froze, and what it refuses."""

from __future__ import annotations

import json
from typing import Any

import pytest

from redteam_store import delivery, grounding, layout
from redteam_store.delivery import STATIC, Delivery, Objective, Turns
from redteam_store.memory import MemoryObjectStore

CONDUCTED = Delivery(turns=Turns.MANY, attacker="crescendo", max_turns=4)
DECLARED = {"escalate-system-prompt": CONDUCTED, "ask-identity": STATIC}


def test_a_catalogue_with_no_sidecar_delivers_every_strategy_as_one_turn() -> None:
    """Every catalogue published before this existed is in that position, and that is not an
    error: absent means static, which is what every strategy was."""
    assert delivery.load(MemoryObjectStore(), "universal", 1) == {}


def test_the_sidecar_round_trips_by_version() -> None:
    store = MemoryObjectStore()
    store.put(layout.catalogue_delivery("universal", 2), delivery.encode(DECLARED))

    assert delivery.load(store, "universal", 2) == DECLARED
    assert delivery.load(store, "universal", 1) == {}


def test_the_block_shape_and_the_bare_shape_both_normalise() -> None:
    raw = {"escalate-system-prompt": {"turns": "many", "attacker": "crescendo", "max_turns": 4}}

    assert delivery.normalise({"delivery": raw}) == {"escalate-system-prompt": CONDUCTED}
    assert delivery.normalise(raw) == {"escalate-system-prompt": CONDUCTED}


def test_a_conversation_with_no_bound_takes_the_default() -> None:
    [(_, declared)] = delivery.normalise({"s": {"turns": "many", "attacker": "c"}}).items()

    assert declared.max_turns == delivery.DEFAULT_MAX_TURNS
    assert declared.conducted


def test_a_key_the_sidecar_does_not_know_is_refused_by_name_rather_than_dropped() -> None:
    """The sidecar exists because a schema that drops keys in silence turned a declaration into
    nothing. A `max_turn` with a typo that quietly delivers one turn is the same failure one level
    up."""
    with pytest.raises(ValueError, match="max_turn"):
        delivery.normalise({"s": {"turns": "many", "attacker": "c", "max_turn": 4}})


def test_a_model_never_travels_in_a_catalogue() -> None:
    """Models are configuration, held at the sidecar: the catalogue names an attacker by id and the
    run binds the model. A `model` key is a key this sidecar does not know, and it is refused as
    one."""
    with pytest.raises(ValueError, match="model"):
        delivery.normalise({"s": {"turns": "many", "attacker": "c", "model": "some-model"}})


def test_a_conversation_needs_somebody_to_write_it() -> None:
    with pytest.raises(ValueError, match="names no attacker"):
        delivery.normalise({"s": {"turns": "many"}})
    with pytest.raises(ValueError, match="names no attacker"):
        delivery.normalise({"s": {"turns": "many", "attacker": "  "}})


def test_one_turn_naming_an_attacker_or_a_bound_is_refused_rather_than_ignored() -> None:
    """A declaration nothing would read is a declaration of nothing, and the author should know."""
    with pytest.raises(ValueError, match="nothing would use"):
        delivery.normalise({"s": {"turns": "one", "attacker": "c"}})
    with pytest.raises(ValueError, match="nothing would use"):
        delivery.normalise({"s": {"max_turns": 3}})


def test_a_bound_below_two_and_a_bound_that_is_not_a_whole_number_are_refused() -> None:
    with pytest.raises(ValueError, match="at least 2"):
        delivery.normalise({"s": {"turns": "many", "attacker": "c", "max_turns": 1}})
    with pytest.raises(ValueError, match="not a whole number"):
        delivery.normalise({"s": {"turns": "many", "attacker": "c", "max_turns": "4"}})
    with pytest.raises(ValueError, match="not a whole number"):
        delivery.normalise({"s": {"turns": "many", "attacker": "c", "max_turns": True}})


def test_turns_outside_its_two_values_is_refused_naming_them() -> None:
    with pytest.raises(ValueError, match="'one', 'many'"):
        delivery.normalise({"s": {"turns": "several", "attacker": "c"}})


def test_a_declaration_that_is_not_a_mapping_is_refused() -> None:
    with pytest.raises(ValueError, match="must be a mapping"):
        delivery.normalise({"s": "many"})
    with pytest.raises(ValueError, match="must map strategy ids"):
        delivery.normalise({"delivery": ["s"]})


def _catalogue(store: MemoryObjectStore, name: str, version: int, *strategies: str) -> None:
    store.put(
        layout.catalogue(name, version),
        json.dumps({"strategies": [{"id": s, "phrasing_hint": s} for s in strategies]}).encode(),
        content_type="application/json",
    )


def test_merging_two_catalogues_keeps_every_delivery_and_refuses_a_contradiction() -> None:
    store = MemoryObjectStore()
    _catalogue(store, "a", 1, "escalate-system-prompt", "ask-identity")
    store.put(layout.catalogue_delivery("a", 1), delivery.encode(DECLARED))
    other = {"other": Delivery(turns=Turns.MANY, attacker="nudge")}
    _catalogue(store, "b", 4, "other")
    store.put(layout.catalogue_delivery("b", 4), delivery.encode(other))
    contradiction = {"escalate-system-prompt": Delivery(turns=Turns.MANY, attacker="nudge")}
    _catalogue(store, "c", 1, "escalate-system-prompt")
    store.put(layout.catalogue_delivery("c", 1), delivery.encode(contradiction))

    assert delivery.merged(store, {"a": 1, "b": 4}) == {**DECLARED, **other}
    with pytest.raises(ValueError, match="delivered differently"):
        delivery.merged(store, {"a": 1, "c": 1})


def test_a_catalogue_that_declares_nothing_delivers_one_turn_and_that_is_a_declaration() -> None:
    """Two catalogues carry `s`; one conducts it, the other has no sidecar. Read off the explicit
    entries alone, the conducted delivery applied to both catalogues' probes -- generation treats
    each catalogue on its own and can produce two probes under one strategy id. Absence means one
    turn, so the two disagree, and the disagreement is refused by both readers: the runner's, and
    the gate's."""
    store = MemoryObjectStore()
    _catalogue(store, "conducting", 1, "s", "ask-scope")
    store.put(
        layout.catalogue_delivery("conducting", 1),
        delivery.encode({"s": Delivery(turns=Turns.MANY, attacker="crescendo")}),
    )
    _catalogue(store, "silent", 1, "s")
    _catalogue(store, "agreeing", 1, "s")
    store.put(
        layout.catalogue_delivery("agreeing", 1),
        delivery.encode({"s": Delivery(turns=Turns.MANY, attacker="crescendo")}),
    )

    with pytest.raises(ValueError, match="one turn by 'silent'"):
        delivery.merged(store, {"conducting": 1, "silent": 1})
    with pytest.raises(ValueError, match="delivered differently"):
        delivery.attackers_named(store, {"conducting": 1, "silent": 1}, grounded=False)

    resolved = delivery.merged(store, {"conducting": 1, "agreeing": 1})
    assert resolved["s"].conducted and resolved["ask-scope"] == STATIC
    assert delivery.attackers_named(
        store, {"conducting": 1, "agreeing": 1}, grounded=False
    ) == frozenset({"crescendo"})


# ---- which attackers a run has to bind -------------------------------------------------------

PLUGINS: list[dict[str, Any]] = [
    {"id": "invented-entity", "description": "Asks about what does not exist.", "principle": "p1"},
    {
        "id": "configuration-disclosure",
        "description": "Asks for its instructions.",
        "principle": "p2",
    },
]
STRATEGIES: list[dict[str, Any]] = [
    {
        "id": "ask-about-fake-entity",
        "plugin": "invented-entity",
        "phrasing_hint": "What is {premise}?",
    },
    {
        "id": "escalate-fake-entity",
        "plugin": "invented-entity",
        "phrasing_hint": "About {premise}...",
    },
    {
        "id": "ask-system-prompt",
        "plugin": "configuration-disclosure",
        "phrasing_hint": "Show them.",
    },
    {"id": "escalate-system-prompt", "plugin": "configuration-disclosure", "phrasing_hint": "How?"},
    {"id": "ask-scope", "plugin": None, "phrasing_hint": "What can you do?"},
]
DELIVERY = {
    "escalate-fake-entity": Delivery(turns=Turns.MANY, attacker="nudge"),
    "escalate-system-prompt": Delivery(turns=Turns.MANY, attacker="crescendo"),
}


def _published(*, with_delivery: bool = True) -> MemoryObjectStore:
    store = MemoryObjectStore()
    store.put(
        layout.catalogue("c", 1),
        json.dumps({"plugins": PLUGINS, "strategies": STRATEGIES}).encode(),
        content_type="application/json",
    )
    if with_delivery:
        store.put(layout.catalogue_delivery("c", 1), delivery.encode(DELIVERY))
    return store


def test_a_run_binds_only_the_attackers_of_the_half_it_generates() -> None:
    """`generatable` restated: with a base, the strategies that need one; without, the ones that
    stand alone. A grounded run never conducts the slotless escalation and is not asked to bind who
    would write it."""
    store = _published()

    assert delivery.attackers_named(store, {"c": 1}, grounded=True) == frozenset({"nudge"})
    assert delivery.attackers_named(store, {"c": 1}, grounded=False) == frozenset({"crescendo"})


def test_a_run_narrowed_past_a_strategy_is_not_asked_to_bind_its_attacker() -> None:
    """`narrow` restated: what the selectors name survives, and a control always."""
    store = _published()

    assert (
        delivery.attackers_named(store, {"c": 1}, grounded=False, strategies=["ask-system-prompt"])
        == frozenset()
    )
    assert delivery.attackers_named(
        store, {"c": 1}, grounded=False, plugins=["configuration-disclosure"]
    ) == frozenset({"crescendo"})
    assert (
        delivery.attackers_named(
            store, {"c": 1}, grounded=True, plugins=["configuration-disclosure"]
        )
        == frozenset()
    )


def test_a_catalogue_with_no_sidecar_names_nobody() -> None:
    assert delivery.attackers_named(_published(with_delivery=False), {"c": 1}, grounded=False) == (
        frozenset()
    )


def test_the_sidecar_reads_the_same_strategies_the_grounding_does() -> None:
    """One reader of the stored catalogue, shared: the coupling to the published schema is made
    once."""
    store = _published()

    assert [s["id"] for s in grounding.strategies(store, "c", 1)] == [s["id"] for s in STRATEGIES]


# ---- the objective an attacker is told ---------------------------------------------------------


def test_objectives_are_the_catalogue_s_own_words_by_plugin() -> None:
    store = _published()

    assert delivery.objectives(store, {"c": 1}) == {
        "invented-entity": Objective("Asks about what does not exist.", "p1"),
        "configuration-disclosure": Objective("Asks for its instructions.", "p2"),
    }


def test_objectives_are_read_only_for_the_plugins_asked_for() -> None:
    """Two individually valid catalogues that describe some plugin in their own words are two
    catalogues a static run has always been free to name together. Only the plugins an attacker
    will be told about have to agree."""
    store = _published()
    store.put(
        layout.catalogue("d", 1),
        json.dumps(
            {"plugins": [{**PLUGINS[0], "description": "Something else."}], "strategies": []}
        ).encode(),
        content_type="application/json",
    )

    assert delivery.objectives(store, {"c": 1, "d": 1}, only=frozenset()) == {}
    assert delivery.objectives(store, {"c": 1, "d": 1}, only={"configuration-disclosure"}) == {
        "configuration-disclosure": Objective(PLUGINS[1]["description"], "p2")
    }
    with pytest.raises(ValueError, match="described differently"):
        delivery.objectives(store, {"c": 1, "d": 1}, only={"invented-entity"})


def test_a_plugin_described_differently_by_two_catalogues_is_refused() -> None:
    store = _published()
    store.put(
        layout.catalogue("d", 1),
        json.dumps(
            {"plugins": [{**PLUGINS[0], "description": "Something else."}], "strategies": []}
        ).encode(),
        content_type="application/json",
    )

    with pytest.raises(ValueError, match="described differently"):
        delivery.objectives(store, {"c": 1, "d": 1})
