"""Reaching an OCI registry for a brain pinned by digest.

`RegistryClient` is the protocol the Boltzmann SDK says is "implemented by the caller", and the
shipped ORAS implementation is right for everything except the one case a run always uses.

**Why this exists.** The shipped client resolves a manifest by building `f"{reference}:{tag}"`,
which is the tag form. A run's `kb_ref` is pinned by digest -- the API refuses anything else,
because a tag moves like a git branch and longitudinal validity needs an oracle nobody can move out
from under a finished run. Handing a digest to the tag slot does not fail; ORAS parses
`ghcr.io/org/brain:sha256:abc` into registry `docker.io`, repository `sha256`, tag `abc`, and asks
Docker Hub for a repository named after the algorithm. What comes back is a 404 about something
nobody was looking for.

So the reference is built here in the form a digest actually takes, `repository@sha256:...`, and
everything else -- authentication, blob download, the digest check the store performs on arrival --
is the shipped client's, unchanged. This is a narrow compensation for one construction, not a
second OCI client.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from boltzmann import BlockStore, OciDigest
    from boltzmann.distribution import BrainManifest

DIGEST_PREFIX = "sha256:"

HTTP_NOT_FOUND = 404
OK_STATUSES = frozenset({200, 201, 202})


def reference_for(repository: str, pin: str) -> str:
    """The reference a registry understands for this pin.

    A digest joins with `@` and a tag with `:`. Both forms are supported because a brain published
    under a moving tag is a legitimate thing to hold -- it is only illegitimate to *measure*
    against one, and that is the API's gate to keep rather than this function's.
    """
    separator = "@" if pin.startswith(DIGEST_PREFIX) else ":"
    return f"{repository}{separator}{pin}"


class DigestAwareRegistry:
    """The shipped ORAS client, with manifest resolution that understands a digest.

    Args:
        insecure: Whether to allow plain HTTP, for a local registry.
        credentials: `(username, password)` for a registry that needs them. A token counts as a
            password. Resolved by the caller from a `secret_ref` -- a frozen spec carries a
            reference and never a credential.
    """

    def __init__(
        self, *, insecure: bool = False, credentials: tuple[str, str] | None = None
    ) -> None:
        from boltzmann.distribution import OrasRegistryClient

        self._inner = OrasRegistryClient(insecure=insecure)
        if credentials is not None:
            username, password = credentials
            self._inner.login(username, password)

    async def resolve(self, reference: str, tag: str) -> BrainManifest:
        """The manifest under this pin, without downloading a module.

        Raises:
            ReferenceNotFoundError: The registry reports nothing under this pin.
            DistributionError: Anything else, including an answer that is not a manifest.
        """
        import oras.defaults
        from boltzmann.distribution import parse_manifest
        from boltzmann.exceptions import DistributionError, ReferenceNotFoundError

        pinned = reference_for(reference, tag)
        registry = self._inner.registry
        try:
            container = registry.get_container(pinned)
            url = f"{registry.prefix}://{container.manifest_url()}"
            accept = ", ".join(oras.defaults.default_manifest_accepted_media_types)
            response = registry.do_request(url, "GET", headers={"Accept": accept})
        except Exception as unreachable:
            # A transport failure rather than a rejection: no status code exists to classify it.
            raise DistributionError(f"cannot reach {pinned}: {unreachable}") from unreachable

        if response.status_code == HTTP_NOT_FOUND:
            raise ReferenceNotFoundError(f"{pinned} is not published")
        if response.status_code not in OK_STATUSES:
            raise DistributionError(
                f"cannot resolve {pinned}: {response.status_code} {response.reason}"
            )
        if not response.content.lstrip().startswith(b"{"):
            raise DistributionError(
                f"cannot resolve {pinned}: the registry answered with "
                f"{response.headers.get('content-type', 'no content type')} rather than a manifest"
            )
        parsed: BrainManifest = parse_manifest(response.content)
        return parsed

    async def pull_blob(self, reference: str, digest: OciDigest, store: BlockStore) -> None:
        """Unchanged: blobs are addressed by the repository alone, which needs no pin."""
        await self._inner.pull_blob(reference, digest, store)

    async def push(self, reference: str, tag: str, *args: Any, **kwargs: Any) -> OciDigest:
        """Refused. The platform consumes brains and never extends one.

        The protocol splits its surface because read and extend are separable, and a read-only
        client is conforming. Implementing this would make the refusal a matter of discipline
        rather than of what the object can do.
        """
        raise NotImplementedError(
            "the platform consumes brains and never publishes one; the write half of the protocol "
            "is deliberately unimplemented"
        )
