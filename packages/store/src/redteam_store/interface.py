"""The object store: append-only, and that is not a configurable policy.

A trace that can be rewritten stops supporting any claim derived from it. So `put` refuses an
existing key rather than overwriting it, and every backend has to honour that -- it is what makes
the evidence evidence. There is no `delete`: nothing the platform writes stops being evidence, and
an interface with no way to remove a key is an interface nobody has to be careful with.

What the store does not do is as load-bearing as what it does. It does not aggregate, filter or
score. It does not know what it holds. And **it does not coordinate**: no locks, no queue, nothing
that waits on anybody. What it does offer is one claim, the only one an append-only store can:
`put` either creates a key or refuses, atomically, and the refusal is the second writer's answer.
Two runners on one run would still repeat work up to their first collision, so the invariant that
prevents two of them -- one process per run -- remains the responsibility of whoever launches; the
claim is what makes the collision loud rather than silent when that invariant slips.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


class ObjectAlreadyExists(Exception):
    """Raised by `put` on a key that is already taken.

    Not an error to route around: for a trace it means the unit already closed, so the caller should
    be skipping it. Resumption relies on this being loud.
    """

    def __init__(self, key: str) -> None:
        super().__init__(f"key already exists and this store only appends: {key}")
        self.key = key


class StoreCannotClaim(RuntimeError):
    """The backend cannot refuse a second write of one key, so nothing built on it is append-only.

    Raised by a backend's `verify()` before the process serves anything, and never routed around: a
    store that overwrites turns every trace into something that can be rewritten and every version
    into something that can be replaced, which is the one property the whole design rests on.
    """

    def __init__(self, where: str, why: str) -> None:
        super().__init__(
            f"the object store at {where!r} does not honour conditional writes ({why}); "
            f"append-only cannot be guaranteed on it, so this process refuses to serve. Use a "
            f"backend that implements `If-None-Match: *` on PutObject -- S3, MinIO and Ceph RGW "
            f"all do."
        )
        self.where = where
        self.why = why


class ObjectNotFound(Exception):
    def __init__(self, key: str) -> None:
        super().__init__(f"no object at key: {key}")
        self.key = key


@runtime_checkable
class ObjectStore(Protocol):
    """The one external dependency the platform has.

    S3-compatible in self-hosted installs, the provider's managed service in the cloud. The
    interface is the seam.
    """

    def put(self, key: str, data: bytes, *, content_type: str | None = None) -> None:
        """Create `key` holding `data`. Raises `ObjectAlreadyExists` if the key is taken.

        **Atomic, or the backend is not a store.** Two callers writing one key must be decided by
        the backend, not by a read that preceded the write; a backend that cannot promise that has
        to say so through `StoreCannotClaim` before it serves, because every caller here treats the
        exception as the record of who was first.
        """
        ...

    def get(self, key: str) -> bytes:
        """Read the object at `key`. Raises `ObjectNotFound` if it is not there."""
        ...

    def exists(self, key: str) -> bool: ...

    def list_prefix(self, prefix: str) -> list[str]:
        """Every key under `prefix`, sorted.

        Sorted because callers diff this against a plan, and an unordered listing turns a cheap set
        difference into a source of nondeterministic bug reports.

        **Read-after-write consistency is an explicit assumption of the design**: resumption takes
        it for granted that a key just written shows up in a listing. Current object services
        guarantee it; any self-hosted implementation has to be checked before a long run is trusted
        to it.
        """
        ...
