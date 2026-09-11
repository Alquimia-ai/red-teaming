"""Building the chat model a run declared, and nothing about which one it should be.

No model id, no provider URL and no embedder name lives in any package -- not as a module constant,
not as a signature default, not through `setdefault`. This module is where that rule is kept honest.
It resolves a **declared** provider to a builder, hands it what the spec says, and refuses when the
spec says nothing rather than falling back on somebody's favourite.

Providers are registered rather than imported at module scope, because none of them is a hard
dependency: a grader takes a `BaseChatModel` and which library builds one is the deployment's
choice. An install without the provider's extra still imports this module -- it simply cannot build
that provider, and says which one it could not build.

**The credential is passed in, not looked up.** Resolving a `secret_ref` is the secrets package's
job, and keeping it out of here is what stops this package from depending on the secrets backend in
every image that grades.

**The rate limiter is built into the model, and that is the whole point.** One 429 on the first
call makes the grader settle its estimator on "this provider has no usable logprobs" and *remember*
the denial, so every later grade raises without calling. `max_retries` does not cover it. Pacing
does -- and since every component receives its model already built, the pacing has to be attached
here or it does not exist.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol

from langchain_core.rate_limiters import BaseRateLimiter, InMemoryRateLimiter
from pydantic import SecretStr

if TYPE_CHECKING:
    from langchain_core.language_models.chat_models import BaseChatModel

    from redteam_contracts.run_spec import ModelSpec

OPENROUTER = "openrouter"
"""A hosted router: one model id served by several upstreams, picked per request."""

OPENAI_COMPATIBLE = "openai_compatible"
"""Any server that speaks the OpenAI chat-completions API at a declared endpoint: vLLM on the
appliance, a provider's own gateway, a proxy. The self-hosted path."""

TEMPERATURE = 0.0
"""Not a taste, and not configurable.

A probe set is content-addressed: two runs over the same knowledge base and catalogue are meant to
share it, and the second skips generation entirely. That property only holds if generation is
deterministic, so a sampled premise would quietly turn one probe set into two. The judge wants zero
for the same reason from the other direction -- a verdict that moves between runs is not an
instrument.
"""

CHECK_EVERY_SECONDS = 0.1
"""How often the limiter wakes to see whether its bucket refilled. Well below any interval worth
setting, so the pacing is the requested rate rather than this granularity."""

MAX_BUCKET_SIZE = 1
"""No burst. A bucket that accumulates permits spends them all at once on the first probe, which is
exactly the burst that draws the 429 this pacing exists to avoid."""

PLACEHOLDER_KEY = "no-credential-declared"
"""What an OpenAI-compatible client is handed when the spec declares no credential.

Non-empty on purpose: the client library reads its own environment for an absent key, which would
measure with a credential nobody declared. A placeholder the server ignores -- or refuses with a 401
that names the problem -- keeps the environment out of it.
"""


class ProviderUndeclared(ValueError):
    """The spec names no provider, so nothing can be built from it.

    Not defaulted, on purpose. A default here is a model nobody declared producing a measurement
    whose provenance nobody wrote down.
    """

    def __init__(self, model: str) -> None:
        super().__init__(
            f"the spec names model {model!r} with no provider. Declare which provider serves it: "
            f"the same model through two providers is two instruments, and the provenance has to "
            f"say which one measured."
        )


class UnknownProvider(ValueError):
    """A provider nothing is registered for. A typo, or a builder nobody registered."""

    def __init__(self, provider: str, known: tuple[str, ...]) -> None:
        super().__init__(
            f"no builder registered for provider {provider!r}. Registered: "
            f"{', '.join(known) or '(none)'}"
        )


class ProviderNotInstalled(RuntimeError):
    """The provider is known and its library is not in this image."""

    def __init__(self, provider: str, distribution: str) -> None:
        super().__init__(
            f"provider {provider!r} needs {distribution!r}, which is not installed in this image"
        )


class CredentialUndeclared(ValueError):
    """A hosted provider asked to build with no credential handed in.

    Omitting the key is not "no key": the client reads its own environment for it and measures
    with whatever the process happens to hold -- a credential the spec never declared. The spec
    names the provider, so the spec names the credential too, by reference, and the resolver hands
    it in. Anything else is refused here, before the client exists.
    """

    def __init__(self, provider: str, model: str) -> None:
        super().__init__(
            f"provider {provider!r} builds {model!r} only with a credential the spec declared, "
            f"and none was handed in. Declare a `secret_ref` on the model: without one the client "
            f"would read whatever key the process holds, which is a credential nobody declared."
        )


class EndpointUndeclared(ValueError):
    """A self-hosted provider asked to build with no endpoint.

    There is no default place an OpenAI-compatible server answers from. Naming one here would be a
    provider URL bound in code, which is the rule this module exists to keep.
    """

    def __init__(self, provider: str, model: str) -> None:
        super().__init__(
            f"provider {provider!r} builds {model!r} only against an endpoint the spec declared "
            f"-- the base URL of the server, `http://judge:8000/v1` for instance -- and none was "
            f"given."
        )


class ProviderBuilder(Protocol):
    """How a provider is constructed. Everything it needs arrives resolved."""

    def __call__(
        self,
        *,
        model: str,
        api_key: str | None,
        endpoint: str | None,
        rate_limiter: BaseRateLimiter | None,
    ) -> BaseChatModel: ...


_PROVIDERS: dict[str, ProviderBuilder] = {}


def register(provider: str, build: ProviderBuilder) -> None:
    """Bind a builder to a provider name.

    Registering the same builder twice is a no-op: this is module state, and a process that imports
    the wiring more than once should not fail for it. Registering a *different* builder under a name
    already taken is refused, because that is the mistake worth catching -- two builders for one
    name means the provenance says `openrouter` and cannot say which `openrouter`.
    """
    existing = _PROVIDERS.get(provider)
    if existing is not None:
        if existing is build:
            return
        raise ValueError(
            f"provider {provider!r} already has a builder; exactly one builder per provider, "
            f"or the provenance cannot say which one ran"
        )
    _PROVIDERS[provider] = build


def registered() -> tuple[str, ...]:
    """Every provider a spec may name in this process."""
    return tuple(sorted(_PROVIDERS))


def pacing(spec: ModelSpec) -> BaseRateLimiter | None:
    """The limiter this spec asks for, or nothing when it asks for none."""
    if spec.requests_per_second is None:
        return None
    return InMemoryRateLimiter(
        requests_per_second=spec.requests_per_second,
        check_every_n_seconds=CHECK_EVERY_SECONDS,
        max_bucket_size=MAX_BUCKET_SIZE,
    )


def build_chat_model(spec: ModelSpec, *, api_key: str | None = None) -> BaseChatModel:
    """The model this spec declares, paced as it asked to be.

    Args:
        spec: What the run froze. `provider` decides the builder; `model` and `endpoint` are handed
            to it verbatim.
        api_key: The credential, already resolved from `spec.secret_ref` by the caller. `None` for a
            provider that needs none. A provider whose client would read its own environment for
            it refuses `None` instead of letting that happen.

    Raises:
        ProviderUndeclared: The spec declares no provider -- `None` or `""`, by the spec's own
            predicate, the one the gate counted it by.
        UnknownProvider: No builder is registered under the declared name.
        ProviderNotInstalled: The builder is registered and its library is absent.
        CredentialUndeclared: A hosted provider was handed no credential.
        EndpointUndeclared: A self-hosted provider was given no endpoint.
    """
    provider = spec.provider if spec.declares_provider() else None
    if provider is None:
        raise ProviderUndeclared(spec.model)
    build = _PROVIDERS.get(provider)
    if build is None:
        raise UnknownProvider(provider, registered())
    return build(
        model=spec.model,
        api_key=api_key,
        endpoint=spec.endpoint,
        rate_limiter=pacing(spec),
    )


ROUTING = {"require_parameters": True}
"""Ask the router not to route to an upstream that ignores a parameter this request sets.

A router serves one model id from several providers and picks per request. They do not all
support `logprobs`, and the default is to route anyway and answer without them. The hint helps
exactly when some upstreams of a model support what was asked for; it cannot conjure logprobs from
a model whose upstreams all lack them -- that is a choice of model, not of routing, and a run whose
judge cannot produce logprobs fails loudly rather than silently sampling.
"""


def _build_openrouter(
    *,
    model: str,
    api_key: str | None,
    endpoint: str | None,
    rate_limiter: BaseRateLimiter | None,
) -> BaseChatModel:
    """The hosted router, for a cloud deployment that serves no models of its own."""
    # Before the import, so the refusal reads the same whether or not the library is installed: a
    # client handed no key reads `OPENROUTER_API_KEY` off the process, and that is the one thing
    # this builder must never let happen.
    if not api_key:
        raise CredentialUndeclared(OPENROUTER, model)
    try:
        from langchain_openrouter import ChatOpenRouter
    except ImportError as missing:
        raise ProviderNotInstalled(OPENROUTER, "langchain-openrouter") from missing

    # The key always, by the alias the generated signature does not expose. The endpoint only when
    # declared: the client reads its own environment for an absent base URL, and an explicit None
    # would override that with nothing. A base URL is not a credential, so that fallback is harmless
    # where the key's was not.
    optional: dict[str, Any] = {"openrouter_api_key": api_key}
    if endpoint:
        optional["openrouter_api_base"] = endpoint

    built: BaseChatModel = ChatOpenRouter(
        model=model,
        temperature=TEMPERATURE,
        rate_limiter=rate_limiter,
        model_kwargs={"provider": ROUTING},
        **optional,
    )
    return built


def _build_openai_compatible(
    *,
    model: str,
    api_key: str | None,
    endpoint: str | None,
    rate_limiter: BaseRateLimiter | None,
) -> BaseChatModel:
    """A server speaking the OpenAI chat-completions API: the appliance's own vLLM, or a gateway.

    The endpoint is required and the credential is not: a server on the appliance's network may
    authenticate nobody, and a spec that declares `self_hosted` without a `secret_ref` is the gate's
    way of saying so. What is never done is leaving the key unset -- see `PLACEHOLDER_KEY`.
    """
    if not endpoint:
        raise EndpointUndeclared(OPENAI_COMPATIBLE, model)
    try:
        from langchain_openai import ChatOpenAI
    except ImportError as missing:
        raise ProviderNotInstalled(OPENAI_COMPATIBLE, "langchain-openai") from missing

    built: BaseChatModel = ChatOpenAI(
        model=model,
        base_url=endpoint,
        api_key=SecretStr(api_key or PLACEHOLDER_KEY),
        temperature=TEMPERATURE,
        rate_limiter=rate_limiter,
    )
    return built


register(OPENROUTER, _build_openrouter)
register(OPENAI_COMPATIBLE, _build_openai_compatible)
