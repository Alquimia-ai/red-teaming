"""Resolving a secret from a reference.

A run spec carries `secret_ref`, never a credential. Two reasons, and the second is the one that
matters more: a spec is frozen and auditable, and a frozen artifact containing a live credential is
a credential with an audit trail pointing at it.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Protocol, runtime_checkable

ENV = "env"
FILE = "file"
AVAILABLE = (ENV, FILE)


class SecretNotFound(KeyError):
    """No secret at the reference: absent, or present and empty.

    Empty counts as absent in every backend. A compose default such as `${OPENROUTER_API_KEY:-}`
    defines the variable as `""`, and handing that on as a credential fails inside the provider
    client, far from its cause, instead of here, by the reference's name, before anything runs.
    """

    def __init__(self, ref: str) -> None:
        super().__init__(f"no secret at reference: {ref}")
        self.ref = ref


@runtime_checkable
class SecretResolver(Protocol):
    def resolve(self, ref: str) -> str: ...


class EnvSecretResolver:
    """Reads from the environment. The local and compose path, and the Kubernetes path when the
    secrets reach the pod as environment variables."""

    def resolve(self, ref: str) -> str:
        value = os.environ.get(ref)
        if not value:
            raise SecretNotFound(ref)
        return value


class FileSecretResolver:
    """Reads a file per secret. A mounted Kubernetes secret is a directory of files."""

    def __init__(self, root: Path) -> None:
        self._root = root

    def resolve(self, ref: str) -> str:
        # A reference is a name, never a path. Without this, `../../etc/passwd` is a valid
        # secret ref.
        if "/" in ref or ".." in ref:
            raise SecretNotFound(ref)
        path = self._root / ref
        if not path.is_file():
            raise SecretNotFound(ref)
        value = path.read_text().strip()
        if not value:
            raise SecretNotFound(ref)
        return value


class SecretsBackendUnavailable(RuntimeError):
    """A backend the settings name and this build cannot serve.

    Loud rather than silently degraded. A resolver that falls back to another backend answers with
    a credential nobody meant to use, or -- worse -- answers `SecretNotFound` for a secret that is
    present in the backend that was actually asked for.
    """


def build_resolver(backend: str, *, root: Path | None = None) -> SecretResolver:
    """The resolver a deployment asked for.

    Takes the backend as a plain string rather than the settings enum, which is what keeps this
    package free of the settings package: the caller already holds the settings, and the selection
    logic belongs in one place rather than copied into every wiring module.

    Args:
        backend: `env` or `file`. The names the settings use.
        root: Where `file` reads from. A mounted secret is a directory of files, one per secret, so
            there is no sensible default -- a wrong root answers "not found" for every secret and
            looks like missing configuration rather than a wrong path.

    Raises:
        SecretsBackendUnavailable: The backend has no implementation here, or `file` was asked for
            with no root.
    """
    if backend == ENV:
        return EnvSecretResolver()
    if backend == FILE:
        if root is None:
            raise SecretsBackendUnavailable(
                "the file secrets backend needs a root directory; without one every lookup "
                "answers 'not found' and reads as missing configuration rather than a wrong path"
            )
        return FileSecretResolver(root)
    raise SecretsBackendUnavailable(
        f"no resolver for the {backend!r} secrets backend in this build. Available: "
        f"{', '.join(AVAILABLE)}"
    )
