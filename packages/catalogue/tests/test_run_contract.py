"""Run-specific grading criteria leave the immutable catalogue untouched."""

from pathlib import Path

import pytest

from redteam_catalogue import assets
from redteam_catalogue.bundle import load_bundle
from redteam_contracts.contract import as_raw, parse_contract_spec
from redteam_store import contract as contract_store
from redteam_store import layout, versioned
from redteam_store.memory import MemoryObjectStore

BASELINE = Path(__file__).resolve().parents[3] / "deploy/seed/catalogues/assistant-baseline.json"
NAME = "assistant-baseline"


@pytest.fixture
def store() -> MemoryObjectStore:
    store = MemoryObjectStore()
    assets.publish_document(store, load_bundle(BASELINE).document)
    return store


def test_remaining_severities_keep_their_proportions_and_the_catalogue_is_unchanged(
    store: MemoryObjectStore,
) -> None:
    original = store.get(layout.catalogue(NAME, 1))
    contract, digest = assets.run_contract(
        store,
        {NAME: 1},
        strategies=("ask-system-prompt", "ask-identity"),
        contract_scope="selected_strategies",
    )
    assert [p.id for p in contract.principles] == ["no_disclosure", "no_misrepresentation"]
    assert [p.weight for p in contract.principles] == pytest.approx([9 / 13, 4 / 13])
    assert sum(p.weight for p in contract.principles) == pytest.approx(1)
    assert parse_contract_spec(contract_store.encode(as_raw(contract))) == contract
    assert digest == versioned.digest(contract_store.encode(as_raw(contract)))
    assert digest != contract_store.digest(store, NAME, 1)
    assert store.get(layout.catalogue(NAME, 1)) == original


@pytest.mark.parametrize("strategy", ["ask-system-prompt", "escalate-system-prompt"])
def test_a_principle_stays_while_one_of_its_strategies_remains(
    store: MemoryObjectStore,
    strategy: str,
) -> None:
    contract, _ = assets.run_contract(
        store,
        {NAME: 1},
        strategies=(strategy,),
        contract_scope="selected_strategies",
    )
    assert [(p.id, p.weight) for p in contract.principles] == [("no_disclosure", 1)]


def test_another_plugin_can_keep_the_same_principle(store: MemoryObjectStore) -> None:
    contract, _ = assets.run_contract(
        store,
        {NAME: 1},
        plugins=("contradicted-fact",),
        strategies=("ask-about-fake-product", "assert-wrong-figure"),
        contract_scope="selected_strategies",
    )
    assert [(p.id, p.weight) for p in contract.principles] == [("no_invention", 1)]


@pytest.mark.parametrize("strategies", [(), ("ask-scope",)])
def test_empty_or_controls_only_selections_are_not_contracts(
    store: MemoryObjectStore,
    strategies: tuple[str, ...],
) -> None:
    with pytest.raises(assets.EmptySelection):
        assets.run_contract(
            store, {NAME: 1}, strategies=strategies, contract_scope="selected_strategies"
        )


def test_legacy_runs_keep_the_full_contract_and_its_digest(store: MemoryObjectStore) -> None:
    assert assets.run_contract(
        store, {NAME: 1}, strategies=("ask-identity",)
    ) == contract_store.shared(
        store,
        {NAME: 1},
    )


def test_filtering_cannot_hide_disagreement_between_catalogue_contracts(
    store: MemoryObjectStore,
) -> None:
    document = load_bundle(BASELINE).document
    contract = {**document.contract, "version": "different"}
    assets.publish_document(
        store, document.model_copy(update={"name": "other", "contract": contract})
    )
    with pytest.raises(contract_store.ContractMismatch):
        assets.run_contract(
            store,
            {NAME: 1, "other": 1},
            strategies=("ask-identity",),
            contract_scope="selected_strategies",
        )
