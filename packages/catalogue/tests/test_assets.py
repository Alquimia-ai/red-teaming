"""Catalogue bundles published to the store, versioned because the store only appends."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from gaussia.schemas.roastme import Catalogue

from redteam_catalogue.assets import (
    CatalogueNotFound,
    EmptySelection,
    Published,
    latest,
    load,
    names,
    narrow,
    versions,
)
from redteam_catalogue.assets import (
    publish as _publish,
)
from redteam_catalogue.bundle import load_bundle
from redteam_catalogue.engines import declared_engines
from redteam_contracts.contract import ContractSpec
from redteam_store import contract as contract_store
from redteam_store import grounding, layout
from redteam_store.delivery import load as load_delivery
from redteam_store.memory import MemoryObjectStore

ROOT = Path(__file__).resolve().parents[3]
CATALOGUES = ROOT / "deploy" / "seed" / "catalogues"
BASELINE = CATALOGUES / "assistant-baseline"


@pytest.fixture
def contract() -> ContractSpec:
    return load_bundle(BASELINE).contract


@pytest.fixture
def universal() -> Catalogue:
    return load_bundle(BASELINE).catalogue


def publish(store: Any, name: str, catalogue: Catalogue, *args: Any, **kwargs: Any) -> Published:
    """`assets.publish`, with the grounding declaration the catalogue implies.

    A wrapper rather than seventeen edited call sites: what these tests are about is versioning and
    collisions, and every one of them would otherwise carry a list that has to be kept in step with
    a fixture. The declaration is required at publish -- see `GroundingMisdeclared` -- and deriving
    it here is what a catalogue's author does by hand.
    """
    kwargs.setdefault("needs_base", _needs_base(catalogue))
    return _publish(store, name, catalogue, *args, **kwargs)


def _needs_base(catalogue: Catalogue) -> list[str]:
    """What the catalogue's own phrasings imply, which is what its author would declare.

    Publishing refuses a premise-bearing strategy that is not declared, so every `publish` here has
    to carry the declaration -- and deriving it keeps these tests about versioning rather than about
    keeping a list in step with a fixture.
    """
    return sorted(s.id for s in catalogue.strategies if "{premise}" in s.phrasing_hint)


def _pieces(catalogue: Catalogue) -> tuple[list[Any], tuple[Any, ...]]:
    """The validation pieces, with the kinds derived from the catalogue under test.

    Derived rather than listed, because that is what publishing does and a hand-written list is a
    second answer to the same question.
    """
    kinds = sorted({strategy.entity_kind for strategy in catalogue.strategies})
    return declared_engines(kinds)


def _revised(catalogue: Catalogue, revision: int) -> Catalogue:
    """The same catalogue with its first strategy renamed: different content, so a new version."""
    first, *rest = catalogue.strategies
    renamed = first.model_copy(update={"id": f"{first.id}-r{revision}"})
    return catalogue.model_copy(update={"strategies": [renamed, *rest]})


def test_publishing_a_change_opens_a_second_version_rather_than_overwriting(
    universal: Catalogue, contract: ContractSpec
) -> None:
    """A catalogue replaced in place makes every finished run's provenance unreadable: the name it
    recorded now resolves to something else."""
    store = MemoryObjectStore()
    engines, transforms = _pieces(universal)

    first = publish(store, "baseline", universal, contract, engines, transforms)
    second = publish(store, "baseline", _revised(universal, 1), contract, engines, transforms)

    assert (first.version, second.version) == (1, 2)
    assert versions(store, "baseline") == (1, 2)
    assert latest(store, "baseline") == 2


def test_publishing_the_same_catalogue_again_writes_nothing(
    universal: Catalogue, contract: ContractSpec
) -> None:
    """A version means different content. A seed re-run and a second replica are one publish."""
    store = MemoryObjectStore()
    engines, transforms = _pieces(universal)

    first = publish(store, "baseline", universal, contract, engines, transforms)
    again = publish(store, "baseline", universal, contract, engines, transforms)

    assert first.created is True
    assert again.created is False
    assert again.version == first.version == 1
    assert versions(store, "baseline") == (1,)


CONDUCTED = {
    "ask-system-prompt": {"turns": "many", "attacker": "crescendo", "max_turns": 4},
    "ask-about-fake-product": {"turns": "many", "attacker": "nudge", "max_turns": 3},
}
"""A delivery over one strategy of each half: one that stands without a premise and one that needs
a base, so the selector tests below have something to select in both shapes of run."""


def test_the_same_catalogue_with_and_without_a_delivery_is_a_different_asset(
    universal: Catalogue, contract: ContractSpec
) -> None:
    """The sidecar decides whether a strategy is one turn or a conversation, so it is part of what
    was published -- the same rule the grounding follows."""
    store = MemoryObjectStore()
    engines, transforms = _pieces(universal)

    bare = publish(store, "baseline", universal, contract, engines, transforms)
    conducted = publish(
        store, "baseline", universal, contract, engines, transforms, delivery=CONDUCTED
    )

    assert (bare.version, conducted.version) == (1, 2)
    assert conducted.created is True
    assert conducted.delivered == ("ask-about-fake-product", "ask-system-prompt")
    assert bare.delivered == ()
    assert set(load_delivery(store, "baseline", 2)) == set(CONDUCTED)
    assert load_delivery(store, "baseline", 1) == {}


def test_a_delivery_over_a_strategy_the_catalogue_does_not_carry_is_refused_by_name(
    universal: Catalogue, contract: ContractSpec
) -> None:
    from redteam_catalogue.assets import DeliveryMisdeclared

    store = MemoryObjectStore()
    engines, transforms = _pieces(universal)

    with pytest.raises(DeliveryMisdeclared, match="no-such-strategy"):
        publish(
            store,
            "baseline",
            universal,
            contract,
            engines,
            transforms,
            delivery={"no-such-strategy": {"turns": "many", "attacker": "crescendo"}},
        )

    assert names(store) == frozenset(), "a refused catalogue leaves the store exactly as it was"


def test_a_delivery_naming_a_model_is_refused_before_a_byte_is_written(
    universal: Catalogue, contract: ContractSpec
) -> None:
    """Models are configuration, held at the publish door: the catalogue names an attacker by id,
    the run binds the model. A `model` key is refused as a key the sidecar does not know, so the
    rule cannot erode into a catalogue that quietly freezes a model choice forever."""
    store = MemoryObjectStore()
    engines, transforms = _pieces(universal)

    with pytest.raises(ValueError, match="model"):
        publish(
            store,
            "baseline",
            universal,
            contract,
            engines,
            transforms,
            delivery={
                "ask-system-prompt": {"turns": "many", "attacker": "c", "model": "some-model"}
            },
        )

    assert names(store) == frozenset()


def test_a_conducted_delivery_over_a_control_is_refused(
    universal: Catalogue, contract: ContractSpec
) -> None:
    """An attacker is steered toward the plugin's objective, and a control has no plugin: a
    conducted control would be a conversation aimed at nothing, and a control that escalates is not
    the same question as the attack."""
    store = MemoryObjectStore()
    engines, transforms = _pieces(universal)
    control = next(s.id for s in universal.strategies if s.plugin is None)

    with pytest.raises(ValueError, match="controls"):
        publish(
            store,
            "baseline",
            universal,
            contract,
            engines,
            transforms,
            delivery={control: {"turns": "many", "attacker": "crescendo"}},
        )

    assert names(store) == frozenset()


@pytest.mark.parametrize(
    ("grounded", "plugins", "strategies"),
    [
        (True, (), ()),
        (False, (), ()),
        (False, ("configuration-disclosure",), ()),
        (False, (), ("ask-identity",)),
        (False, (), ("ask-system-prompt",)),
        (True, ("invented-entity",), ()),
        (True, (), ("ask-about-fake-product",)),
        (True, (), ("assert-wrong-figure",)),
        (True, ("contradicted-fact",), ()),
    ],
)
def test_the_gate_s_notion_of_in_play_matches_narrow_over_generatable(
    universal: Catalogue,
    contract: ContractSpec,
    grounded: bool,
    plugins: tuple[str, ...],
    strategies: tuple[str, ...],
) -> None:
    """The store's `attackers_named` restates the two rules that decide which strategies a run
    generates, because the store may not depend on gaussia. This pins the restatement to the
    originals: a change to `generatable` or `narrow` that the restatement does not follow fails here
    rather than in a run refused for an attacker it would never build."""
    from redteam_catalogue.assets import generatable
    from redteam_store.delivery import attackers_named

    store = MemoryObjectStore()
    engines, transforms = _pieces(universal)
    publish(store, "baseline", universal, contract, engines, transforms, delivery=CONDUCTED)

    half = generatable(universal, grounded=grounded, declared=frozenset(_needs_base(universal)))
    in_play = narrow(half, plugins, strategies)
    expected = frozenset(
        CONDUCTED[s.id]["attacker"] for s in in_play.strategies if s.id in CONDUCTED
    )

    assert (
        attackers_named(
            store, {"baseline": 1}, grounded=grounded, plugins=plugins, strategies=strategies
        )
        == expected
    )


def test_the_newest_version_is_read_off_a_sorted_listing(
    universal: Catalogue, contract: ContractSpec
) -> None:
    """The store exposes no timestamp, so the version has to be readable from the keys."""
    store = MemoryObjectStore()
    engines, transforms = _pieces(universal)
    for revision in range(11):
        publish(store, "baseline", _revised(universal, revision), contract, engines, transforms)
    assert latest(store, "baseline") == 11


def test_a_catalogue_naming_an_unknown_construction_is_refused(
    universal: Catalogue, contract: ContractSpec
) -> None:
    """A refused catalogue leaves the store exactly as it was."""
    store = MemoryObjectStore()
    engines, transforms = _pieces(universal)
    broken = universal.model_copy(
        update={
            "strategies": [
                universal.strategies[0].model_copy(update={"transform": "not_a_construction"}),
                *universal.strategies[1:],
            ]
        }
    )

    with pytest.raises(ValueError, match="transforms outside"):
        publish(store, "broken", broken, contract, engines, transforms)
    assert names(store) == frozenset()


def test_an_unpublished_name_is_refused_rather_than_answered_empty() -> None:
    with pytest.raises(CatalogueNotFound):
        load(MemoryObjectStore(), "never-published")


def test_what_comes_back_is_what_went_in(universal: Catalogue, contract: ContractSpec) -> None:
    store = MemoryObjectStore()
    engines, transforms = _pieces(universal)
    publish(store, "baseline", universal, contract, engines, transforms)
    assert load(store, "baseline") == universal
    assert contract_store.load(store, "baseline", 1).principle_ids == contract.principle_ids


class _DiesOnce:
    """The real store, except that the first write of one key dies: a publish killed between its
    two writes."""

    def __init__(self, inner: MemoryObjectStore, key: str) -> None:
        self._inner = inner
        self._key = key
        self.died = False

    def put(self, key: str, data: bytes, *, content_type: str | None = None) -> None:
        if key == self._key and not self.died:
            self.died = True
            raise RuntimeError("the process died before the write landed")
        self._inner.put(key, data, content_type=content_type)

    def get(self, key: str) -> bytes:
        return self._inner.get(key)

    def exists(self, key: str) -> bool:
        return self._inner.exists(key)

    def list_prefix(self, prefix: str) -> list[str]:
        return self._inner.list_prefix(prefix)


def test_naming_nothing_leaves_the_catalogue_whole(universal: Catalogue) -> None:
    assert narrow(universal) == universal


def test_narrowing_to_a_plugin_keeps_its_strategies(universal: Catalogue) -> None:
    narrowed = narrow(universal, plugins=["contradicted-fact"])
    attacks = {s.id for s in narrowed.strategies if s.plugin is not None}
    assert attacks == {"assert-wrong-figure", "assert-wrong-date"}
    assert {p.id for p in narrowed.plugins} == {"contradicted-fact"}


def test_narrowing_always_keeps_the_controls(universal: Catalogue) -> None:
    """A control is the only thing separating "the assistant is careful" from "the questions were
    easy". Dropping it leaves a run with a numerator and no way to read the denominator."""
    narrowed = narrow(universal, plugins=["contradicted-fact"])
    assert any(strategy.plugin is None for strategy in narrowed.strategies)


def test_narrowing_to_a_strategy_keeps_only_it(universal: Catalogue) -> None:
    narrowed = narrow(universal, strategies=["ask-about-fake-product"])
    attacks = {s.id for s in narrowed.strategies if s.plugin is not None}
    assert attacks == {"ask-about-fake-product"}


def test_a_selection_that_attacks_nothing_is_refused(universal: Catalogue) -> None:
    """An empty probe set measures nothing while every artifact downstream reports itself
    complete."""
    with pytest.raises(EmptySelection):
        narrow(universal, plugins=["no-such-plugin"])


def test_a_premise_bearing_strategy_left_undeclared_is_refused_by_name(
    universal: Catalogue, contract: ContractSpec
) -> None:
    """The declaration is the catalogue's statement of which strategies need a base, so it has to
    be complete -- and an incomplete one is caught here, at a rejected publish, rather than by a run
    that sends `"What does cover?"` to somebody's assistant."""
    from redteam_catalogue.assets import GroundingMisdeclared

    store = MemoryObjectStore()
    engines, transforms = _pieces(universal)
    complete = _needs_base(universal)
    missing = complete[0]

    with pytest.raises(GroundingMisdeclared, match=missing):
        _publish(
            store,
            "baseline",
            universal,
            contract,
            engines,
            transforms,
            needs_base=[d for d in complete if d != missing],
        )

    assert names(store) == frozenset(), "a refused catalogue leaves the store exactly as it was"


def test_a_strategy_that_stands_alone_may_still_be_declared_as_needing_a_base(
    universal: Catalogue, contract: ContractSpec
) -> None:
    """The case the sidecar exists for, and the reason it is not merely the slots restated.

    gaussia appends the premise to a phrasing with no slot, on its other branch. A catalogue that
    wants that has to be able to ask for it, so declaring a slotless strategy is allowed -- what is
    refused is the opposite, a slotted one left undeclared.
    """
    store = MemoryObjectStore()
    engines, transforms = _pieces(universal)
    standing = next(s.id for s in universal.strategies if "{premise}" not in s.phrasing_hint)

    published = _publish(
        store,
        "baseline",
        universal,
        contract,
        engines,
        transforms,
        needs_base=[*_needs_base(universal), standing],
    )

    assert published.version == 1
    assert standing in grounding.load(store, "baseline", 1)


def test_the_contract_lands_beside_the_catalogue_and_a_changed_contract_is_a_new_version(
    universal: Catalogue, contract: ContractSpec
) -> None:
    """The contract is part of the bundle: the same catalogue under a revised contract is a
    different asset, and each version reads its own contract back."""
    store = MemoryObjectStore()
    engines, transforms = _pieces(universal)
    first = publish(store, "baseline", universal, contract, engines, transforms)

    revised_raw = {
        "version": "v2",
        "verdict": {
            "positive": list(contract.positive_tokens),
            "negative": list(contract.negative_tokens),
        },
        "principles": [
            {"id": p.id, "weight": p.weight, "rubric": p.rubric + " Answer carefully."}
            for p in contract.principles
        ],
    }
    from redteam_contracts.contract import parse_contract_spec

    revised = parse_contract_spec(__import__("json").dumps(revised_raw))
    second = publish(store, "baseline", universal, revised, engines, transforms)

    assert (first.version, second.version) == (1, 2)
    assert first.contract_digest != second.contract_digest
    assert first.principles == second.principles == len(contract.principles)
    assert contract_store.load(store, "baseline", 1).version == contract.version
    assert contract_store.load(store, "baseline", 2).version == "v2"
    assert store.exists(layout.catalogue_contract("baseline", 1))


def test_a_plugin_charging_a_principle_the_contract_does_not_carry_is_refused_by_name(
    universal: Catalogue, contract: ContractSpec
) -> None:
    """The reason the contract travels in the bundle: a plugin and a principle revised apart would
    let a published catalogue charge something nobody can grade."""
    store = MemoryObjectStore()
    engines, transforms = _pieces(universal)
    broken = universal.model_copy(
        update={
            "plugins": [
                universal.plugins[0].model_copy(update={"principle": "no_such_principle"}),
                *universal.plugins[1:],
            ]
        }
    )

    with pytest.raises(ValueError, match="no_such_principle"):
        publish(store, "baseline", broken, contract, engines, transforms)
    assert names(store) == frozenset(), "a refused bundle leaves the store exactly as it was"


def test_a_publish_that_dies_before_its_contract_lands_leaves_no_version_without_one(
    universal: Catalogue, contract: ContractSpec
) -> None:
    """The contract goes first, so a death before it lands leaves nothing at all -- never a
    catalogue version nobody can grade and nothing can ever add a contract to."""
    inner = MemoryObjectStore()
    engines, transforms = _pieces(universal)
    dying = _DiesOnce(inner, layout.catalogue_contract("baseline", 1))

    with pytest.raises(RuntimeError):
        publish(dying, "baseline", universal, contract, engines, transforms)

    assert versions(inner, "baseline") == ()
    assert not inner.exists(layout.catalogue_contract("baseline", 1))

    completed = publish(inner, "baseline", universal, contract, engines, transforms)
    assert (completed.version, versions(inner, "baseline")) == (1, (1,))


def test_a_publish_that_dies_after_its_contract_lands_is_completed_by_the_next_one(
    universal: Catalogue, contract: ContractSpec
) -> None:
    """An orphan sidecar is not a version to the listing, and the next publish of exactly this
    bundle completes it at that version rather than stepping over it. A retry after a crash is that
    publish."""
    inner = MemoryObjectStore()
    engines, transforms = _pieces(universal)
    dying = _DiesOnce(inner, layout.catalogue("baseline", 1))

    with pytest.raises(RuntimeError):
        publish(dying, "baseline", universal, contract, engines, transforms)

    assert versions(inner, "baseline") == ()
    assert inner.exists(layout.catalogue_contract("baseline", 1)), (
        "the sidecar was not written first"
    )

    completed = publish(inner, "baseline", universal, contract, engines, transforms)
    assert (completed.version, versions(inner, "baseline")) == (1, (1,))
    assert completed.created is True


def test_an_orphan_sidecar_of_another_bundle_is_stepped_over(
    universal: Catalogue, contract: ContractSpec
) -> None:
    """A different contract cannot complete somebody else's half-published version: that version is
    skipped, and since the listing ignores sidecars, `latest` skips it too."""
    store = MemoryObjectStore()
    engines, transforms = _pieces(universal)
    store.put(layout.catalogue_contract("baseline", 1), b'{"version":"somebody-else"}')

    published = publish(store, "baseline", universal, contract, engines, transforms)

    assert published.version == 2
    assert versions(store, "baseline") == (2,)
    assert latest(store, "baseline") == 2


@pytest.mark.parametrize("sidecar", ["contract", "grounding", "delivery"])
def test_sidecar_inserted_after_selection_cannot_mix_the_bundle(
    universal: Catalogue, contract: ContractSpec, monkeypatch: pytest.MonkeyPatch, sidecar: str
) -> None:
    import redteam_catalogue.assets as module
    from redteam_store.versioned import digest

    store = MemoryObjectStore()
    engines, transforms = _pieces(universal)
    original = module._next_version
    inserted = False

    def interleave(*args: Any) -> int:
        nonlocal inserted
        chosen = original(*args)
        if not inserted:
            inserted = True
            spell = {
                "contract": layout.catalogue_contract,
                "grounding": layout.catalogue_grounding,
                "delivery": layout.catalogue_delivery,
            }[sidecar]
            store.put(spell("baseline", chosen), b'{"foreign":true}')
        return chosen

    monkeypatch.setattr(module, "_next_version", interleave)
    result = publish(store, "baseline", universal, contract, engines, transforms)
    assert result.version == 2
    assert result.contract_digest == digest(store.get(layout.catalogue_contract("baseline", 2)))
    assert not store.exists(layout.catalogue("baseline", 1))
    assert not store.exists(layout.catalogue_delivery("baseline", 2))


@pytest.mark.parametrize("identical", [True, False])
def test_publishers_interleaved_at_claim_commit_consistent_bundles(
    universal: Catalogue, contract: ContractSpec, monkeypatch: pytest.MonkeyPatch, identical: bool
) -> None:
    store = MemoryObjectStore()
    engines, transforms = _pieces(universal)
    original = store.put
    other = universal if identical else _revised(universal, 2)
    entered = False

    def interleave(key: str, data: bytes, *, content_type: str | None = None) -> None:
        nonlocal entered
        if key == layout.catalogue_claim("baseline", 1) and not entered:
            entered = True
            publish(store, "baseline", other, contract, engines, transforms)
        original(key, data, content_type=content_type)

    monkeypatch.setattr(store, "put", interleave)
    result = publish(store, "baseline", universal, contract, engines, transforms)
    assert result.version == (1 if identical else 2)
    assert result.created is not identical
    assert load(store, "baseline", result.version) == universal
    assert len(versions(store, "baseline")) == (1 if identical else 2)


def test_identical_publish_completed_during_version_selection_is_reused(
    universal: Catalogue, contract: ContractSpec, monkeypatch: pytest.MonkeyPatch
) -> None:
    import redteam_catalogue.assets as module

    store = MemoryObjectStore()
    engines, transforms = _pieces(universal)
    original = module._next_version
    entered = False

    def interleave(*args: Any) -> int:
        nonlocal entered
        if not entered:
            entered = True
            publish(store, "baseline", universal, contract, engines, transforms)
        return original(*args)

    monkeypatch.setattr(module, "_next_version", interleave)
    result = publish(store, "baseline", universal, contract, engines, transforms)
    assert result.version == 1 and not result.created
    assert versions(store, "baseline") == (1,)


@pytest.mark.parametrize("with_delivery", [False, True])
def test_competing_optional_sidecars_are_reserved_as_part_of_the_bundle(
    universal: Catalogue,
    contract: ContractSpec,
    monkeypatch: pytest.MonkeyPatch,
    with_delivery: bool,
) -> None:
    from redteam_store.delivery import load as load_delivery

    store = MemoryObjectStore()
    engines, transforms = _pieces(universal)
    original = store.put
    entered = False

    def interleave(key: str, data: bytes, *, content_type: str | None = None) -> None:
        nonlocal entered
        if key == layout.catalogue_contract("baseline", 1) and not entered:
            entered = True
            publish(
                store,
                "baseline",
                universal,
                contract,
                engines,
                transforms,
                delivery=None if with_delivery else CONDUCTED,
            )
        original(key, data, content_type=content_type)

    monkeypatch.setattr(store, "put", interleave)
    result = publish(
        store,
        "baseline",
        universal,
        contract,
        engines,
        transforms,
        delivery=CONDUCTED if with_delivery else None,
    )
    assert result.version == 1
    assert versions(store, "baseline") == (1, 2)
    assert bool(load_delivery(store, "baseline", 1)) is with_delivery
    assert bool(load_delivery(store, "baseline", 2)) is not with_delivery
