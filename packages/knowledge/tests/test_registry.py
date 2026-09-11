"""A digest is not a tag, and the shipped client cannot tell the difference.

The failure this guards is silent. `ghcr.io/org/brain:sha256:abc` is not rejected by ORAS -- it is
parsed into registry `docker.io`, repository `sha256`, tag `abc`, so a run pinned to a digest asks
Docker Hub for a repository named after the hash algorithm and gets a 404 about something nobody
was looking for.
"""

from __future__ import annotations

import pytest

from redteam_knowledge.registry import reference_for

REPOSITORY = "ghcr.io/alquimia-ai/brain"
DIGEST = "sha256:abc123"


def test_a_digest_joins_with_an_at_sign() -> None:
    assert reference_for(REPOSITORY, DIGEST) == f"{REPOSITORY}@{DIGEST}"


def test_a_tag_joins_with_a_colon() -> None:
    """Both forms are supported: holding a brain under a moving tag is legitimate. Measuring
    against one is not, and that is the API's gate to keep rather than this function's."""
    assert reference_for(REPOSITORY, "v2") == f"{REPOSITORY}:v2"


def test_the_digest_form_addresses_the_repository_the_run_named() -> None:
    """The assertion that catches it: what ORAS resolves each reference to."""
    oras = pytest.importorskip("oras.container")

    wrong = oras.Container(f"{REPOSITORY}:{DIGEST}")
    right = oras.Container(reference_for(REPOSITORY, DIGEST))

    assert wrong.manifest_url() == "docker.io/v2/sha256/manifests/abc123"
    assert right.manifest_url() == f"ghcr.io/v2/alquimia-ai/brain/manifests/{DIGEST}"


def test_the_reader_never_publishes() -> None:
    """The write half of the protocol is unimplemented by construction, not by discipline."""
    import asyncio

    from redteam_knowledge.registry import DigestAwareRegistry

    async def attempt() -> None:
        registry = DigestAwareRegistry.__new__(DigestAwareRegistry)
        await registry.push(REPOSITORY, "v1")

    with pytest.raises(NotImplementedError, match="never publishes"):
        asyncio.run(attempt())
