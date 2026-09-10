"""A store backend the settings name and this build cannot serve is refused, loudly."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from redteam_store.backends import AVAILABLE, StoreBackendUnavailable, build_store
from redteam_store.memory import MemoryObjectStore


@dataclass
class _Settings:
    store_backend: str = "s3"
    s3_bucket: str = "red-teaming"
    s3_endpoint: str | None = "http://minio:9000"
    s3_region: str | None = None
    s3_access_key: str | None = "k"
    s3_secret_key: str | None = "s"


def test_memory_is_served() -> None:
    assert isinstance(build_store("memory", _Settings()), MemoryObjectStore)


def test_a_backend_nothing_implements_refuses_to_serve() -> None:
    """A selection that fell through to a default would start green and write a client's evidence
    to whatever S3-shaped endpoint happened to be configured."""
    with pytest.raises(StoreBackendUnavailable, match="gcs"):
        build_store("gcs", _Settings())


def test_the_refusal_says_what_this_build_can_actually_serve() -> None:
    """A refusal naming only what failed leaves the reader guessing at the fix."""
    with pytest.raises(StoreBackendUnavailable) as refused:
        build_store("nonsense", _Settings())
    for available in AVAILABLE:
        assert available in str(refused.value)


def test_the_settings_promise_exactly_what_this_build_serves() -> None:
    """The enum is the contract the operator reads; it must not name a backend nothing serves, and
    this build must not serve one the operator cannot select."""
    from redteam_settings.config import StoreBackend

    assert {backend.value for backend in StoreBackend} == set(AVAILABLE)
