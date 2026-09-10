"""The natural-query prior: the engagement's traffic, versioned because the store only appends."""

from __future__ import annotations

import pytest

from redteam_store.memory import MemoryObjectStore
from redteam_store.priors import (
    EmptyPrior,
    PriorNotFound,
    latest,
    load,
    publish,
    versions,
)

POOL = ["qué cubre mi seguro?", "cuánto es el deducible", "  qué cubre mi seguro?  ", ""]


def test_publishing_normalises_and_versions() -> None:
    store = MemoryObjectStore()
    first = publish(store, "acme", POOL)
    second = publish(store, "acme", [*POOL, "cómo cancelo la póliza"])

    assert (first.version, second.version) == (1, 2)
    assert first.size == 2, "trimmed, deduplicated, and the empty string dropped"
    assert load(store, "acme", 1) == ("qué cubre mi seguro?", "cuánto es el deducible")
    assert latest(store, "acme") == 2
    assert versions(store, "acme") == (1, 2)


def test_publishing_the_same_pool_again_writes_nothing() -> None:
    """Normalised first, so a pool that differs only in whitespace and duplicates is the same pool
    -- and the same pool is one version, whoever publishes it and however often."""
    store = MemoryObjectStore()
    first = publish(store, "acme", POOL)
    again = publish(store, "acme", ["qué cubre mi seguro?", " cuánto es el deducible ", "", ""])

    assert (first.created, again.created) == (True, False)
    assert again.version == 1
    assert versions(store, "acme") == (1,)


def test_an_empty_pool_is_refused_before_it_reaches_a_run() -> None:
    """gaussia refuses it at the estimator. Here is earlier and cheaper: a run should not be
    accepted, generate probes and profile an assistant before finding out its realism budget
    compares against nothing."""
    with pytest.raises(EmptyPrior):
        publish(MemoryObjectStore(), "acme", ["", "   "])


def test_an_unpublished_name_is_refused_rather_than_answered_empty() -> None:
    with pytest.raises(PriorNotFound):
        load(MemoryObjectStore(), "nobody")
