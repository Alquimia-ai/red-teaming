"""The model factory refuses rather than guesses, and the pacing arrives attached.

Every assertion here is about a refusal or about provenance. That is the whole job of this module:
a model nobody declared is a measurement nobody can attribute, so the interesting behaviour is what
happens when the spec is silent.
"""

from __future__ import annotations

import pytest
from langchain_core.rate_limiters import InMemoryRateLimiter

from redteam_contracts.run_spec import ModelSpec
from redteam_contracts.serving import ServingPath
from redteam_judges import models


class _Recorder:
    """A builder that records what it was handed instead of reaching a provider."""

    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def __call__(self, **kwargs: object) -> object:
        self.calls.append(kwargs)
        return object()


@pytest.fixture
def provider(request: pytest.FixtureRequest) -> str:
    """A provider name unique to this test.

    The registry is module state and refuses a second builder under one name, which is the rule
    worth having. Naming the provider after the test respects it rather than reaching in to reset
    it -- a test that has to undo production state is testing something the production path never
    does.
    """
    return f"fixture-{request.node.name}"


@pytest.fixture
def recorder(provider: str) -> _Recorder:
    build = _Recorder()
    models.register(provider, build)  # type: ignore[arg-type]  # a stand-in, not a chat model
    return build


@pytest.mark.parametrize("provider", [None, ""])
def test_a_spec_with_no_provider_is_refused(provider: str | None) -> None:
    """The failure this module exists to prevent: a default provider nobody declared. An empty name
    declares none either, and is refused as undeclared rather than as unknown."""
    with pytest.raises(models.ProviderUndeclared):
        models.build_chat_model(ModelSpec(model="some/model", provider=provider))


def test_an_unregistered_provider_names_what_is_registered() -> None:
    with pytest.raises(models.UnknownProvider) as refused:
        models.build_chat_model(ModelSpec(model="some/model", provider="not-a-provider"))
    assert "not-a-provider" in str(refused.value)


def test_a_hosted_provider_never_builds_on_the_process_s_own_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Handed no key, the router's client reads `OPENROUTER_API_KEY` off the process and measures
    with a credential the spec never declared. The builder refuses before the client exists, and
    says what the spec has to declare."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "an-ambient-key-nobody-declared")
    with pytest.raises(models.CredentialUndeclared, match="secret_ref"):
        models.build_chat_model(ModelSpec(model="some/model", provider=models.OPENROUTER))


def test_the_builder_receives_what_the_spec_declared(recorder: _Recorder, provider: str) -> None:
    models.build_chat_model(
        ModelSpec(model="some/model", provider=provider, endpoint="https://example.invalid"),
        api_key="secret",
    )
    handed = recorder.calls[-1]
    assert handed["model"] == "some/model"
    assert handed["endpoint"] == "https://example.invalid"
    assert handed["api_key"] == "secret"


def test_pacing_is_attached_to_the_model_when_asked_for(recorder: _Recorder, provider: str) -> None:
    """One 429 makes the grader remember the denial and stop measuring in silence.

    Retries do not cover that, so the limiter has to be part of the model rather than something a
    caller remembers to wrap around it.
    """
    models.build_chat_model(
        ModelSpec(model="some/model", provider=provider, requests_per_second=2.0)
    )
    assert isinstance(recorder.calls[-1]["rate_limiter"], InMemoryRateLimiter)


def test_no_pacing_is_the_absence_of_a_limiter_rather_than_an_unlimited_one(
    recorder: _Recorder, provider: str
) -> None:
    models.build_chat_model(ModelSpec(model="some/model", provider=provider))
    assert recorder.calls[-1]["rate_limiter"] is None


def test_registering_the_same_builder_twice_is_a_no_op(recorder: _Recorder, provider: str) -> None:
    """The wiring is imported more than once per process and must not fail for it."""
    models.register(provider, recorder)  # type: ignore[arg-type]  # a stand-in, not a chat model


def test_registering_a_different_builder_under_one_name_is_refused(
    recorder: _Recorder, provider: str
) -> None:
    """Two builders for one name means the provenance says a provider and cannot say which one."""
    with pytest.raises(ValueError, match="already has a builder"):
        models.register(provider, _Recorder())  # type: ignore[arg-type]  # a stand-in


def test_serving_path_follows_where_the_model_runs() -> None:
    """Not a deployment detail: the same model yields a different kind of number by serving path."""
    assert ModelSpec(model="m").serving_path is ServingPath.HOSTED_API
    assert ModelSpec(model="m", self_hosted=True).serving_path is ServingPath.SELF_HOSTED


def test_the_self_hosted_provider_needs_an_endpoint_and_never_reads_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The appliance's own server has no default address, and the client library reads
    `OPENAI_API_KEY` off the process for an absent key -- so the endpoint is required and an
    undeclared credential becomes an explicit placeholder rather than an ambient read."""
    pytest.importorskip("langchain_openai")
    monkeypatch.setenv("OPENAI_API_KEY", "an-ambient-key-nobody-declared")

    with pytest.raises(models.EndpointUndeclared, match="endpoint"):
        models.build_chat_model(ModelSpec(model="local/judge", provider=models.OPENAI_COMPATIBLE))

    built = models.build_chat_model(
        ModelSpec(
            model="local/judge",
            provider=models.OPENAI_COMPATIBLE,
            endpoint="http://judge:8000/v1",
            self_hosted=True,
        )
    )
    key = built.openai_api_key  # type: ignore[attr-defined]
    assert key.get_secret_value() == models.PLACEHOLDER_KEY
    assert built.openai_api_base == "http://judge:8000/v1"  # type: ignore[attr-defined]
    assert built.temperature == models.TEMPERATURE  # type: ignore[attr-defined]


def test_a_declared_credential_reaches_the_self_hosted_client() -> None:
    pytest.importorskip("langchain_openai")
    built = models.build_chat_model(
        ModelSpec(
            model="local/judge", provider=models.OPENAI_COMPATIBLE, endpoint="http://judge/v1"
        ),
        api_key="declared",
    )
    assert built.openai_api_key.get_secret_value() == "declared"  # type: ignore[attr-defined]


def test_both_shipped_providers_are_registered_on_import() -> None:
    assert {models.OPENROUTER, models.OPENAI_COMPATIBLE} <= set(models.registered())
