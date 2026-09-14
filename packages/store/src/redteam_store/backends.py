"""Which store a deployment asked for, decided once.

Every process that touches the store -- the API, the runner -- selects its backend here rather than
branching on the enum itself. One copy of a selection is one place to add a backend and none to
forget, and the conditional-write check every process must run before it serves is run here.

**A backend the settings name and this build cannot serve is refused, loudly.** A selection that
falls through to a default starts green and writes a client's evidence to whatever S3-shaped
endpoint happens to be configured, which is worse than not starting: the operator reads the enum as
the contract, and nothing says otherwise until somebody goes looking for objects that are not
where they were meant to be.

Takes the backend as a plain string rather than the settings enum, which is what keeps this package
free of the settings package -- the same shape `redteam_secrets.build_resolver` has, and for the
same reason.
"""

from __future__ import annotations

from typing import Protocol

from redteam_store.interface import ObjectStore

S3 = "s3"
MEMORY = "memory"
AVAILABLE = (S3, MEMORY)
"""What this build can actually serve. The settings enum promises exactly this and nothing more."""


class StoreBackendUnavailable(RuntimeError):
    """A store backend the settings name and this build cannot serve.

    Loud rather than silently degraded, and louder than most: the store is where a run's evidence
    lives, so a process that silently serves a different one writes traces nobody will find and
    reads a plan that is not there.
    """


class S3Settings(Protocol):
    """The connection values required by the S3 adapter."""

    @property
    def s3_bucket(self) -> str: ...
    @property
    def s3_endpoint(self) -> str | None: ...
    @property
    def s3_access_key(self) -> str | None: ...
    @property
    def s3_secret_key(self) -> str | None: ...
    @property
    def s3_region(self) -> str | None: ...


def build_store(backend: str, settings: S3Settings, *, verify: bool = True) -> ObjectStore:
    """The store this deployment asked for, checked before it is used.

    Args:
        backend: `s3` or `memory`. The names the settings use.
        settings: Where the S3 endpoint, region and credentials come from.
        verify: Whether to prove the bucket honours conditional writes before returning. Always, in
            production: append-only is what makes the evidence evidence, and a backend that
            performs a second write of one key gives none of it. `False` only for a caller that has
            already verified this process's store.

    Raises:
        StoreBackendUnavailable: The backend has no adapter here.
        StoreCannotClaim: The bucket does not refuse a second write of one key.
    """
    if backend == MEMORY:
        from redteam_store.memory import MemoryObjectStore

        return MemoryObjectStore()
    if backend == S3:
        from redteam_store.s3 import S3ObjectStore

        s3 = S3ObjectStore(
            bucket=settings.s3_bucket,
            endpoint_url=settings.s3_endpoint,
            access_key=settings.s3_access_key,
            secret_key=settings.s3_secret_key,
            region=settings.s3_region,
        )
        if verify:
            # Before the first key is written: "this key exists" and "this unit closed" are one
            # statement only on a bucket that refuses the second writer.
            s3.verify()
        return s3
    raise StoreBackendUnavailable(
        f"no adapter for the {backend!r} store backend in this build. Available: "
        f"{', '.join(AVAILABLE)}. This process refuses to serve rather than writing a run's "
        f"evidence somewhere nobody asked for."
    )
