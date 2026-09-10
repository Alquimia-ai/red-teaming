"""Publishing and reading a versioned asset: the mechanics every published asset shares.

The catalogue bundles and the natural-query priors are two different things with one storage
discipline. Each is the engagement's asset rather than ours, each changes on the client's cadence,
and each has to be readable back at the version a finished run used -- so each is published under
`{root}/{name}/v{00001}.json` and never overwritten, because the store only appends.

Here once: listing the names, listing a name's versions, resolving the newest, reading one, and
writing the next. What stays with each asset is the part that is actually its own -- what a valid
one looks like, what an empty one means, and what it refuses.

Nothing here knows what an asset contains. It moves bytes and counts versions.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass

from redteam_store import layout
from redteam_store.interface import ObjectAlreadyExists, ObjectNotFound, ObjectStore

FIRST_VERSION = 1

CLAIM_ATTEMPTS = 3
"""How many versions a publish tries to claim before giving up.

A collision means another publisher landed the version this one listed as free. Stepping to the
next one is the right response exactly once or twice -- two people publishing at the same moment --
and wrong as a loop: a publisher that never lands is a listing that never catches up, which is a
store problem, not a race.
"""


@dataclass(frozen=True)
class Kind:
    """One kind of published asset: where its versions live, and what to raise when none do.

    `missing` takes the text to report rather than a structured value, because callers raise it
    both for a name that has nothing published and for a name at a version that does not exist,
    and those read differently.
    """

    root: str
    label: str
    missing: Callable[[str], Exception]


@dataclass(frozen=True)
class Published:
    """Where a version landed, and the digest of exactly the bytes that landed there."""

    name: str
    version: int
    key: str
    digest: str
    created: bool = True
    """Whether this publish wrote the version, or found it already there with these exact bytes.

    False is not a failure: it is the answer to a publisher that sent what is already published --
    a seed script re-run, a second replica coming up, a retry after a lost response. The version it
    names is the one those bytes live at, and nothing was written.
    """


def digest(payload: bytes) -> str:
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


def names(store: ObjectStore, kind: Kind) -> frozenset[str]:
    """Every name of this kind with at least one published version."""
    found = set()
    for key in store.list_prefix(kind.root + "/"):
        parsed = layout.parse_asset(kind.root, key)
        if parsed is not None:
            found.add(parsed[0])
    return frozenset(found)


def versions(store: ObjectStore, kind: Kind, name: str) -> tuple[int, ...]:
    """The published versions of one name, ascending."""
    return tuple(
        sorted(
            parsed[1]
            for key in store.list_prefix(layout.asset_prefix(kind.root, kind.label, name) + "/")
            if (parsed := layout.parse_asset(kind.root, key)) is not None
        )
    )


def latest(store: ObjectStore, kind: Kind, name: str) -> int:
    """The newest published version, or refuse.

    Read off a sorted listing rather than from a timestamp, because the store exposes none -- and a
    version number the publisher assigned is a fact anybody can check against the keys.
    """
    published = versions(store, kind, name)
    if not published:
        raise kind.missing(name)
    return published[-1]


def read(store: ObjectStore, kind: Kind, name: str, version: int | None = None) -> bytes:
    """One version's bytes. The newest when no version is named."""
    resolved = latest(store, kind, name) if version is None else version
    try:
        return store.get(layout.asset(kind.root, kind.label, name, resolved))
    except ObjectNotFound as absent:
        raise kind.missing(f"{name} v{resolved}") from absent


def write(store: ObjectStore, kind: Kind, name: str, payload: bytes) -> Published:
    """Write the next version, or find these bytes already published as the newest one.

    A version means different content. Publishing exactly what the newest version holds writes
    nothing and answers with that version, `created=False`, so a seed script that runs twice and
    two replicas that come up together do not open a second version of one asset.

    A concurrent publish of the same version collides in the store rather than overwriting: the
    store's `put` is a claim, and the loser lists again and takes the next number. Two publishers
    of different content land as two versions and nobody's bytes disappear. After `CLAIM_ATTEMPTS`
    collisions the last one is raised, because a listing that never catches up is the store's
    problem and not a race.

    Raises:
        ObjectAlreadyExists: Every version this publish tried to claim was taken first.
    """
    for _ in range(CLAIM_ATTEMPTS):
        published = versions(store, kind, name)
        if published:
            newest = layout.asset(kind.root, kind.label, name, published[-1])
            if store.get(newest) == payload:
                return Published(name, published[-1], newest, digest(payload), created=False)
        version = (published[-1] + 1) if published else FIRST_VERSION
        key = layout.asset(kind.root, kind.label, name, version)
        try:
            store.put(key, payload, content_type="application/json")
        except ObjectAlreadyExists as taken:
            collision = taken
            continue
        return Published(name=name, version=version, key=key, digest=digest(payload))
    raise collision
