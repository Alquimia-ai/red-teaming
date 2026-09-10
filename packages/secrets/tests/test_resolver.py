"""Selecting a secrets backend, and refusing the ones this build cannot serve.

The interesting cases are the refusals. A resolver that quietly falls back answers `SecretNotFound`
for a secret that is present in the backend that was actually asked for, which reads as missing
configuration and sends whoever debugs it to the wrong place.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from redteam_secrets.resolver import (
    AVAILABLE,
    EnvSecretResolver,
    FileSecretResolver,
    SecretNotFound,
    SecretsBackendUnavailable,
    build_resolver,
)


def test_the_env_backend_reads_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TARGET_KEY", "a-credential")
    assert isinstance(build_resolver("env"), EnvSecretResolver)
    assert build_resolver("env").resolve("TARGET_KEY") == "a-credential"


def test_the_file_backend_reads_one_file_per_secret(tmp_path: Path) -> None:
    (tmp_path / "TARGET_KEY").write_text("a-credential\n")
    resolver = build_resolver("file", root=tmp_path)
    assert isinstance(resolver, FileSecretResolver)
    assert resolver.resolve("TARGET_KEY") == "a-credential"


def test_an_empty_environment_value_is_not_a_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    """Compose defaults an unset key to `""` (`${OPENROUTER_API_KEY:-}`). Handed on as a credential,
    that surfaces as the provider client's own validation error far from its cause, instead of the
    `SecretNotFound` that names the reference and stops the run at the gate."""
    monkeypatch.setenv("EMPTY_KEY", "")
    with pytest.raises(SecretNotFound, match="EMPTY_KEY"):
        build_resolver("env").resolve("EMPTY_KEY")


def test_an_empty_secret_file_is_not_a_secret(tmp_path: Path) -> None:
    """Same rule, every backend: a mounted file holding a newline is a secret somebody forgot."""
    (tmp_path / "EMPTY_KEY").write_text("\n")
    with pytest.raises(SecretNotFound, match="EMPTY_KEY"):
        build_resolver("file", root=tmp_path).resolve("EMPTY_KEY")


def test_the_file_backend_without_a_root_is_refused() -> None:
    """Every lookup would answer 'not found', which reads as missing configuration."""
    with pytest.raises(SecretsBackendUnavailable, match="root directory"):
        build_resolver("file")


def test_a_backend_with_no_implementation_is_refused_rather_than_substituted() -> None:
    with pytest.raises(SecretsBackendUnavailable) as refused:
        build_resolver("vault")
    for available in AVAILABLE:
        assert available in str(refused.value)


def test_the_settings_promise_exactly_what_this_build_serves() -> None:
    """The enum is the contract the operator reads; it must not name a backend nothing serves."""
    from redteam_settings.config import SecretsBackend

    assert {backend.value for backend in SecretsBackend} == set(AVAILABLE)


def test_a_reference_is_a_name_and_never_a_path(tmp_path: Path) -> None:
    """Without this, `../../etc/passwd` is a valid secret ref."""
    resolver = build_resolver("file", root=tmp_path)
    with pytest.raises(SecretNotFound):
        resolver.resolve("../../etc/passwd")
