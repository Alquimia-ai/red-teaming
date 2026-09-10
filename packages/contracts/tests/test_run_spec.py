"""The spec carries references and numbers, and nothing that would make it unrepresentable."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from redteam_contracts.run_spec import ConnectorSpec, ModelSpec, RunSpec
from redteam_contracts.serving import ServingPath


def _spec(**overrides: object) -> RunSpec:
    fields: dict[str, object] = {
        "run_id": "run-1",
        "catalogues": ("base",),
        "plugins": (),
        "strategies": (),
        "connector": ConnectorSpec(kind="alquimia", endpoint="http://rt", secret_ref="TOKEN"),
        "judge": ModelSpec(model="judge-1", provider="openrouter", secret_ref="JUDGE_KEY"),
        "replicas": 2,
    }
    fields.update(overrides)
    return RunSpec.model_validate(fields)


def test_a_minimal_spec_round_trips_through_json() -> None:
    spec = _spec()
    assert RunSpec.model_validate_json(spec.model_dump_json()) == spec
    assert spec.kb_ref is None and spec.exploit is None and spec.webhook_url is None
    assert spec.catalogue_versions == {}


def test_a_target_that_can_act_is_representable_and_says_so() -> None:
    """Whether attacking it is *allowed* is the gate's question; the spec only records the fact."""
    spec = _spec(
        connector=ConnectorSpec(
            kind="alquimia",
            endpoint="http://rt",
            secret_ref="TOKEN",
            declared_capabilities=("payments",),
            safe_mode=True,
        )
    )
    assert spec.connector.can_act


def test_a_model_records_where_it_is_served() -> None:
    hosted = ModelSpec(model="m", provider="openrouter", secret_ref="K")
    local = ModelSpec(model="m", provider="openai_compatible", endpoint="http://judge:8000/v1")
    assert hosted.serving_path is ServingPath.HOSTED_API
    assert not hosted.self_hosted
    assert ModelSpec(model="m", self_hosted=True).serving_path is ServingPath.SELF_HOSTED
    assert local.declares_provider() and not ModelSpec(model="m", provider="").declares_provider()


def test_the_spec_is_frozen() -> None:
    spec = _spec()
    with pytest.raises(ValidationError):
        spec.replicas = 3


def test_replicas_start_at_one() -> None:
    with pytest.raises(ValidationError):
        _spec(replicas=0)
