"""The storage discipline every published asset shares, tested once where it lives."""

from __future__ import annotations

import pytest

from redteam_store import layout, versioned
from redteam_store.interface import ObjectAlreadyExists
from redteam_store.memory import MemoryObjectStore


class _Missing(KeyError):
    def __init__(self, what: str) -> None:
        super().__init__(f"nothing published for {what!r}")


KIND = versioned.Kind(root=layout.CATALOGUES, label="catalogue", missing=_Missing)


def test_the_first_version_is_one_and_they_ascend() -> None:
    store = MemoryObjectStore()
    assert versioned.write(store, KIND, "base", b"a").version == 1
    assert versioned.write(store, KIND, "base", b"b").version == 2
    assert versioned.versions(store, KIND, "base") == (1, 2)


def test_the_newest_is_read_off_a_sorted_listing() -> None:
    """The store exposes no timestamp, so the padded key is what orders versions. Ten has to come
    after nine, which is what the padding is for."""
    store = MemoryObjectStore()
    for revision in range(11):
        versioned.write(store, KIND, "base", f"revision {revision}".encode())
    assert versioned.latest(store, KIND, "base") == 11
    assert versioned.read(store, KIND, "base") == b"revision 10"


def test_publishing_what_the_newest_version_holds_writes_nothing() -> None:
    """A version means different content. A seed script re-run and a second replica coming up are
    not two versions of one asset; they are one publish, answered twice."""
    store = MemoryObjectStore()
    first = versioned.write(store, KIND, "base", b"same")
    again = versioned.write(store, KIND, "base", b"same")

    assert first.created is True
    assert again.created is False
    assert again.version == first.version == 1
    assert again.key == first.key
    assert versioned.versions(store, KIND, "base") == (1,)


def test_an_older_version_s_content_is_still_a_new_version() -> None:
    """Only the newest is compared: republishing v1's bytes after v2 is a change back, and a change
    is a version."""
    store = MemoryObjectStore()
    versioned.write(store, KIND, "base", b"a")
    versioned.write(store, KIND, "base", b"b")
    assert versioned.write(store, KIND, "base", b"a").version == 3


class _Raced(MemoryObjectStore):
    """A store where somebody else lands the first `n` versions this publisher tries to claim."""

    def __init__(self, collisions: int) -> None:
        super().__init__()
        self._collisions = collisions
        self.attempted: list[str] = []

    def put(self, key: str, data: bytes, *, content_type: str | None = None) -> None:
        self.attempted.append(key)
        if self._collisions:
            self._collisions -= 1
            super().put(key, b"somebody else's bytes", content_type=content_type)
            raise ObjectAlreadyExists(key)
        super().put(key, data, content_type=content_type)


def test_a_collision_takes_the_next_version_rather_than_overwriting() -> None:
    """Two publishers of different content land as two versions; nobody's bytes disappear."""
    store = _Raced(collisions=1)
    written = versioned.write(store, KIND, "base", b"mine")

    assert written.version == 2
    assert written.created is True
    assert versioned.read(store, KIND, "base", 1) == b"somebody else's bytes"
    assert versioned.read(store, KIND, "base", 2) == b"mine"


def test_a_publisher_that_never_lands_gives_up_loudly() -> None:
    """A listing that never catches up is a store problem, not a race, and looping would hide it."""
    store = _Raced(collisions=versioned.CLAIM_ATTEMPTS)
    with pytest.raises(ObjectAlreadyExists):
        versioned.write(store, KIND, "base", b"mine")
    assert len(store.attempted) == versioned.CLAIM_ATTEMPTS


def test_a_version_is_never_overwritten() -> None:
    """Append-only is what makes a finished run's provenance readable: the version it recorded has
    to still mean what it meant."""
    store = MemoryObjectStore()
    written = versioned.write(store, KIND, "base", b"first")
    with pytest.raises(ObjectAlreadyExists):
        store.put(written.key, b"second")
    assert versioned.read(store, KIND, "base", 1) == b"first"


def test_a_name_with_nothing_published_raises_the_kinds_own_error() -> None:
    """Each asset refuses in its own words -- `PriorNotFound` is what its callers catch, and the
    core must not flatten every kind into one error."""
    store = MemoryObjectStore()
    with pytest.raises(_Missing, match="base"):
        versioned.latest(store, KIND, "base")
    with pytest.raises(_Missing, match="base v3"):
        versioned.read(store, KIND, "base", 3)


def test_the_digest_is_of_the_bytes_that_landed() -> None:
    store = MemoryObjectStore()
    written = versioned.write(store, KIND, "base", b"content")
    assert written.digest == versioned.digest(b"content")
    assert written.digest == versioned.digest(store.get(written.key))


def test_names_lists_only_what_has_a_version() -> None:
    store = MemoryObjectStore()
    versioned.write(store, KIND, "base", b"x")
    versioned.write(store, KIND, "other", b"x")
    store.put(f"{layout.CATALOGUES}/stray/not-a-version.json", b"x")
    store.put(layout.catalogue_contract("base", 1), b"{}")
    assert versioned.names(store, KIND) == frozenset({"base", "other"})


def test_kinds_do_not_see_each_other() -> None:
    """Two assets in one bucket. A listing that leaked across roots would report a prior as a
    catalogue version."""
    store = MemoryObjectStore()
    priors = versioned.Kind(root=layout.PRIORS, label="prior", missing=_Missing)
    versioned.write(store, KIND, "shared-name", b"x")
    assert versioned.names(store, priors) == frozenset()
    assert versioned.versions(store, priors, "shared-name") == ()
