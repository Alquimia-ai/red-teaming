"""The contract sidecar: read by the version a run froze, and shared by every catalogue it named."""

from __future__ import annotations

import json
from typing import Any

import pytest

from redteam_store import contract, layout
from redteam_store.memory import MemoryObjectStore

CONTRACT: dict[str, Any] = {
    "version": "v1",
    "verdict": {"positive": ["YES"], "negative": ["NO"]},
    "principles": [
        {"id": "no_invention", "weight": 0.7, "rubric": "Must not invent."},
        {"id": "no_disclosure", "weight": 0.3, "rubric": "Must not disclose."},
    ],
}


def _published(store: MemoryObjectStore, name: str, version: int, raw: dict[str, Any]) -> None:
    store.put(layout.catalogue_contract(name, version), contract.encode(raw))
    store.put(
        layout.catalogue(name, version), json.dumps({"plugins": [], "strategies": []}).encode()
    )


def test_the_sidecar_reads_back_as_the_contract_the_version_carries() -> None:
    store = MemoryObjectStore()
    _published(store, "base", 1, CONTRACT)

    spec = contract.load(store, "base", 1)

    assert spec.principle_ids == frozenset({"no_invention", "no_disclosure"})
    assert contract.digest(store, "base", 1) == contract.digest(store, "base", 1)


def test_a_version_without_a_contract_is_refused_rather_than_defaulted() -> None:
    """A catalogue whose plugins charge principles nobody declared cannot be graded."""
    store = MemoryObjectStore()
    with pytest.raises(contract.ContractMissing, match="v1"):
        contract.load(store, "base", 1)


def test_formatting_does_not_change_the_digest_but_a_weight_does() -> None:
    """Two catalogues that published the same declaration agree, however it was formatted; two
    that differ in one weight do not."""
    store = MemoryObjectStore()
    _published(store, "a", 1, CONTRACT)
    reordered = {
        "principles": CONTRACT["principles"],
        "verdict": CONTRACT["verdict"],
        "version": "v1",
    }
    _published(store, "b", 2, reordered)
    changed = {
        **CONTRACT,
        "principles": [
            {**CONTRACT["principles"][0], "weight": 0.6},
            {**CONTRACT["principles"][1], "weight": 0.4},
        ],
    }
    _published(store, "c", 1, changed)

    assert contract.digest(store, "a", 1) == contract.digest(store, "b", 2)
    assert contract.digest(store, "a", 1) != contract.digest(store, "c", 1)


def test_a_run_over_several_catalogues_needs_one_contract() -> None:
    store = MemoryObjectStore()
    _published(store, "a", 1, CONTRACT)
    _published(store, "b", 3, CONTRACT)
    _published(store, "c", 1, {**CONTRACT, "version": "v2"})

    spec, digest = contract.shared(store, {"a": 1, "b": 3})
    assert spec.version == "v1"
    assert digest == contract.digest(store, "a", 1)

    with pytest.raises(contract.ContractMismatch, match="2 different contracts") as refused:
        contract.shared(store, {"a": 1, "b": 3, "c": 1})
    assert "c v1" in str(refused.value) and "a v1" in str(refused.value)


def test_shared_refuses_an_empty_selection_and_a_missing_sidecar() -> None:
    store = MemoryObjectStore()
    with pytest.raises(ValueError, match="at least one catalogue"):
        contract.shared(store, {})
    with pytest.raises(contract.ContractMissing):
        contract.shared(store, {"ghost": 1})
