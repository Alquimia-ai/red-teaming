"""The natural-query prior, published to the store and read from it.

The pool of phrasings a category's generated queries are measured against, so that a category which
drifts into stilted or overtly adversarial wording is penalised. gaussia ships no pool and says why:
the user's own traffic is what makes the estimate mean anything. An invented pool measures our
imagination.

The storage discipline is `redteam_store.versioned`, shared with every other published asset. What
is this asset's own is here: a pool is a list of strings, an empty one is refused, and phrasings are
deduplicated in the order they arrived.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass

from redteam_store import layout, versioned
from redteam_store.interface import ObjectStore

FIRST_VERSION = versioned.FIRST_VERSION


class PriorNotFound(KeyError):
    def __init__(self, name: str) -> None:
        super().__init__(f"no natural-query prior published under the name {name!r}")
        self.name = name


class EmptyPrior(ValueError):
    """A pool with nothing in it, refused before it reaches a run.

    gaussia refuses it too, at construction of the estimator. Refusing at publish is earlier and
    cheaper: a run should not be accepted, generate probes and profile an assistant before finding
    out its realism budget compares against nothing.
    """


KIND = versioned.Kind(root=layout.PRIORS, label="prior", missing=PriorNotFound)


@dataclass(frozen=True)
class PublishedPrior:
    name: str
    version: int
    key: str
    digest: str
    size: int
    created: bool = True
    """False when these exact phrasings were already the newest version: nothing was written."""


def names(store: ObjectStore) -> frozenset[str]:
    return versioned.names(store, KIND)


def versions(store: ObjectStore, name: str) -> tuple[int, ...]:
    return versioned.versions(store, KIND, name)


def latest(store: ObjectStore, name: str) -> int:
    return versioned.latest(store, KIND, name)


def load(store: ObjectStore, name: str, version: int | None = None) -> tuple[str, ...]:
    """The pool, as a tuple of phrasings. The newest version when none is named."""
    return tuple(json.loads(versioned.read(store, KIND, name, version)))


def normalise(phrasings: Sequence[str]) -> tuple[str, ...]:
    """Trimmed, deduplicated in order, and refused when nothing is left."""
    seen: dict[str, None] = {}
    for phrasing in phrasings:
        text = str(phrasing).strip()
        if text:
            seen.setdefault(text, None)
    if not seen:
        raise EmptyPrior("a natural-query prior needs at least one phrasing real users send")
    return tuple(seen)


def encode(pool: Sequence[str]) -> bytes:
    return json.dumps(list(pool), ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def publish(store: ObjectStore, name: str, phrasings: Sequence[str]) -> PublishedPrior:
    pool = normalise(phrasings)
    written = versioned.write(store, KIND, name, encode(pool))
    return PublishedPrior(
        name=written.name,
        version=written.version,
        key=written.key,
        digest=written.digest,
        size=len(pool),
        created=written.created,
    )
