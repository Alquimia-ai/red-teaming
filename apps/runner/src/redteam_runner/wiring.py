"""Compose generation clients from deployment configuration and credential references."""

from __future__ import annotations

from langchain_core.language_models.chat_models import BaseChatModel

from redteam_contracts.run_spec import ModelSpec
from redteam_knowledge.registry import DigestAwareRegistry
from redteam_secrets.resolver import SecretResolver
from redteam_settings.config import Settings


def generator_for(spec: ModelSpec | None, resolver: SecretResolver) -> BaseChatModel | None:
    """The generator the run declared, built through the resolver, or none.

    None is legal and common: it is only needed by a construction that writes premises with a
    model, and a catalogue naming one without it is refused by name at build time.

    The credential comes from the resolver and never from the environment.
    """
    if spec is None:
        return None
    from redteam_judges.models import build_chat_model

    credential = resolver.resolve(spec.secret_ref) if spec.secret_ref else None
    return build_chat_model(spec, api_key=credential)


def brain_registry(settings: Settings, resolver: SecretResolver) -> DigestAwareRegistry:
    """The registry client, with credentials resolved from the reference the settings name.

    The settings carry a `secret_ref` and never a credential: a frozen, auditable artifact holding
    a live token is a token with an audit trail pointing at it.
    """
    from redteam_knowledge.registry import DigestAwareRegistry

    credentials: tuple[str, str] | None = None
    if settings.brain_registry_secret_ref:
        raw = resolver.resolve(settings.brain_registry_secret_ref)
        username, _, password = raw.partition(":")
        credentials = (username, password)
    return DigestAwareRegistry(insecure=settings.brain_registry_insecure, credentials=credentials)
