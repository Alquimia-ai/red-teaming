"""The entry gate: none of its checks costs a conversation with the assistant."""

from __future__ import annotations

import re

import pytest
from pydantic import ValidationError

from redteam_api.validation import ValidationFailure, resolve_versions, validate
from redteam_contracts.kb import BrainRef
from redteam_contracts.run_spec import Budget, ConnectorSpec, ModelSpec, RunSpec

CATALOGUES = frozenset({"baseline"})


def _spec(**overrides: object) -> RunSpec:
    base: dict[str, object] = {
        "run_id": "run-1",
        "brain": BrainRef(registry="ghcr.io", repository="acme/kb", digest="sha256:" + "a" * 64),
        "catalogues": ("baseline",),
        "plugins": (),
        "strategies": (),
        "connector": ConnectorSpec(kind="alquimia", endpoint="https://rt", secret_ref="TARGET_KEY"),
        "judge": ModelSpec(model="a/b"),
        "replicas": 3,
    }
    base.update(overrides)
    return RunSpec.model_validate(base)


def test_a_well_formed_run_passes() -> None:
    validate(_spec(), known_catalogues=CATALOGUES)


@pytest.mark.parametrize("outside", ["Run_1", "run.1", "RUN-1", "-run", "a" * 51])
def test_a_run_id_outside_the_rule_is_refused_naming_the_rule(outside: str) -> None:
    with pytest.raises(ValidationFailure, match="does not follow the rule"):
        validate(_spec(run_id=outside), known_catalogues=CATALOGUES)


def test_a_tag_only_knowledge_base_is_refused() -> None:
    with pytest.raises(ValidationError, match="String should match pattern"):
        BrainRef(registry="ghcr.io", repository="acme/kb", digest="v1")


def test_an_unknown_catalogue_is_refused_and_the_published_ones_named() -> None:
    with pytest.raises(ValidationFailure, match="unknown catalogues") as refused:
        validate(_spec(catalogues=("nope",)), known_catalogues=CATALOGUES)
    assert "baseline" in str(refused.value)


def test_a_run_naming_no_catalogue_is_refused() -> None:
    with pytest.raises(ValidationFailure, match="at least one catalogue"):
        validate(_spec(catalogues=()), known_catalogues=CATALOGUES)


def test_a_connector_kind_nothing_builds_is_refused_by_name() -> None:
    http = ConnectorSpec(kind="http", endpoint="http://t", secret_ref="K")
    with pytest.raises(ValidationFailure, match="'http'") as refused:
        validate(_spec(connector=http), known_catalogues=CATALOGUES)
    assert "alquimia" in str(refused.value) and "replay" in str(refused.value)


def test_a_ceiling_nothing_enforces_is_refused_rather_than_accepted_in_silence() -> None:
    with pytest.raises(ValidationFailure, match="max_tokens") as refused:
        validate(_spec(budget=Budget(max_tokens=1000)), known_catalogues=CATALOGUES)
    assert "max_target_calls" in str(refused.value) and "max_wall_seconds" in str(refused.value)
    validate(
        _spec(budget=Budget(max_target_calls=10, max_wall_seconds=3600)),
        known_catalogues=CATALOGUES,
    )


def test_an_acting_target_without_a_sandbox_is_refused_and_with_one_accepted() -> None:
    acting = ConnectorSpec(
        kind="alquimia",
        endpoint="https://rt",
        secret_ref="TARGET_KEY",
        declared_capabilities=("transfer_funds",),
        safe_mode=False,
    )
    with pytest.raises(ValidationFailure, match="sandbox agreement"):
        validate(_spec(connector=acting), known_catalogues=CATALOGUES)
    validate(
        _spec(connector=acting.model_copy(update={"safe_mode": True})), known_catalogues=CATALOGUES
    )


HOSTED = ModelSpec(model="a/b", provider="openrouter")
HOSTED_EMBEDDER = ModelSpec(model="a/b", provider="openrouter", endpoint="http://e")


@pytest.mark.parametrize(
    ("overrides", "role"),
    [
        ({"judge": HOSTED}, "judge"),
        ({"generator": HOSTED}, "generator"),
        ({"embedder": HOSTED_EMBEDDER}, "embedder"),
        ({"attackers": {"nudge": HOSTED}}, "attackers['nudge']"),
    ],
)
def test_a_hosted_model_without_a_secret_reference_is_refused_naming_the_role(
    overrides: dict[str, object], role: str
) -> None:
    """A hosted client handed no key reads the process's own -- a credential the spec never
    declared. Refused here, before, and by role."""
    with pytest.raises(ValidationFailure, match=re.escape(role)):
        validate(_spec(**overrides), known_catalogues=CATALOGUES)


def test_a_stand_in_judge_and_a_self_hosted_model_need_no_secret_reference() -> None:
    validate(
        _spec(
            judge=ModelSpec(model="stand-in"),
            generator=ModelSpec(
                model="qwen", provider="openai_compatible", endpoint="http://vllm", self_hosted=True
            ),
        ),
        known_catalogues=CATALOGUES,
    )


def test_an_attacker_a_catalogue_names_and_the_spec_does_not_bind_is_refused_by_name() -> None:
    with pytest.raises(ValidationFailure, match="crescendo"):
        validate(_spec(), known_catalogues=CATALOGUES, attackers_named=frozenset({"crescendo"}))
    validate(
        _spec(attackers={"crescendo": ModelSpec(model="a/b")}),
        known_catalogues=CATALOGUES,
        attackers_named=frozenset({"crescendo"}),
    )


def test_an_attacker_nothing_the_run_generates_names_is_inert() -> None:
    validate(_spec(attackers={"unused": ModelSpec(model="a/b")}), known_catalogues=CATALOGUES)


def test_a_model_driven_construction_needs_the_run_s_context_and_generator() -> None:
    """A construction that writes premises with a model is refused here rather than after a pulled
    brain, and the refusal names what is missing."""
    with pytest.raises(ValidationFailure, match="contextual_sibling") as refused:
        validate(
            _spec(), known_catalogues=CATALOGUES, model_driven=frozenset({"contextual_sibling"})
        )
    assert "context" in str(refused.value) and "generator" in str(refused.value)

    declared = _spec(
        context={"language": "es-419", "domain": "banca"},
        generator=ModelSpec(model="g", provider="openrouter", secret_ref="GEN_KEY"),
    )
    validate(declared, known_catalogues=CATALOGUES, model_driven=frozenset({"contextual_sibling"}))

    no_provider = declared.model_copy(update={"generator": ModelSpec(model="g")})
    with pytest.raises(ValidationFailure, match="no generator"):
        validate(
            no_provider, known_catalogues=CATALOGUES, model_driven=frozenset({"contextual_sibling"})
        )


def test_a_secret_reference_in_the_platform_s_own_namespace_is_refused_naming_the_role() -> None:
    reserved = ModelSpec(model="a/b", provider="openrouter", secret_ref="REDTEAM_S3_ENDPOINT")
    with pytest.raises(ValidationFailure, match=re.escape("attackers['nudge']")):
        validate(_spec(attackers={"nudge": reserved}), known_catalogues=CATALOGUES)
    connector = ConnectorSpec(kind="replay", endpoint="replay://", secret_ref="REDTEAM_S3_BUCKET")
    with pytest.raises(ValidationFailure, match="connector"):
        validate(_spec(connector=connector), known_catalogues=CATALOGUES)


def test_versions_resolve_to_the_pin_or_the_newest_and_a_bad_pin_is_refused() -> None:
    published = {"baseline": 3, "other": 1}
    assert resolve_versions(_spec(), published) == {"baseline": 3}
    assert resolve_versions(_spec(catalogue_versions={"baseline": 2}), published) == {"baseline": 2}
    assert resolve_versions(_spec(catalogues=("baseline", "nope")), published) == {"baseline": 3}
    with pytest.raises(ValidationFailure, match="version 7"):
        resolve_versions(_spec(catalogue_versions={"baseline": 7}), published)
    with pytest.raises(ValidationFailure, match="version 0"):
        resolve_versions(_spec(catalogue_versions={"baseline": 0}), published)
