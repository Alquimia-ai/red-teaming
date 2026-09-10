"""POST /runs: what gets frozen into `spec.json`, what reaches the runner, and how a retry reads."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from redteam_api import deps
from redteam_api.main import app
from redteam_catalogue import assets
from redteam_catalogue.bundle import load_bundle
from redteam_catalogue.engines import declared_engines
from redteam_contracts.run_spec import RunSpec
from redteam_dispatch import AlreadyRunning, JobHandle, JobState
from redteam_store import layout
from redteam_store.memory import MemoryObjectStore

ROOT = Path(__file__).resolve().parents[3]
BASELINE = ROOT / "deploy" / "seed" / "catalogues" / "assistant-baseline"
CATALOGUE = "assistant-baseline"
RecordingDispatcher = Any
"""The recording dispatcher the `dispatcher` fixture hands in; typed loosely here because the
fixture module is not importable by an absolute name."""

STANDING = {
    "ask-identity",
    "ask-system-prompt",
    "escalate-system-prompt",
    "act-for-another",
    "refuse-escalation",
    "ask-scope",
}


def _spec(run_id: str, **overrides: Any) -> dict[str, Any]:
    """A brainless run over the seed: the standing half generates, and it conducts
    `escalate-system-prompt` through `crescendo`, so the attacker has to be bound."""
    base: dict[str, Any] = {
        "run_id": run_id,
        "kb_ref": None,
        "catalogues": [CATALOGUE],
        "plugins": [],
        "strategies": [],
        "connector": {
            "kind": "alquimia",
            "endpoint": "https://runtime.example/api",
            "secret_ref": "TARGET_KEY",
            "declared_capabilities": [],
            "safe_mode": True,
            "options": {"assistant_id": "asst-1"},
        },
        "judge": {"model": "stand-in"},
        "attackers": {
            "crescendo": {
                "model": "attacker",
                "provider": "openai_compatible",
                "endpoint": "http://vllm/v1",
                "self_hosted": True,
            }
        },
        "replicas": 1,
    }
    base.update(overrides)
    return base


def test_a_run_is_frozen_with_its_versions_pinned_and_a_runner_launched(
    client: TestClient, store: MemoryObjectStore, dispatcher: RecordingDispatcher
) -> None:
    response = client.post("/runs", json=_spec("run-frozen"))

    assert response.status_code == 202, response.text
    body = response.json()
    assert body["result_location"] == layout.manifest("run-frozen")
    assert body["catalogue_versions"] == {CATALOGUE: 1}
    assert body["launched"] is True
    frozen = RunSpec.model_validate_json(store.get(layout.spec("run-frozen")))
    assert frozen.catalogue_versions == {CATALOGUE: 1}
    assert dispatcher.launched == [("run-frozen", ("TARGET_KEY",))]


def test_the_newest_version_is_pinned_and_a_pin_the_consumer_made_is_kept(
    client: TestClient, store: MemoryObjectStore
) -> None:
    bundle = load_bundle(BASELINE)
    first, *rest = bundle.catalogue.strategies
    revised = bundle.catalogue.model_copy(
        update={"strategies": [first.model_copy(update={"id": f"{first.id}-v2"}), *rest]}
    )
    assets.publish(
        store,
        CATALOGUE,
        revised,
        bundle.contract,
        *declared_engines(bundle.entity_kinds),
        needs_base=sorted(assets.needs_a_base(revised, bundle.needs_base)),
        delivery=bundle.delivery,
    )

    newest = client.post("/runs", json=_spec("run-newest"))
    pinned = client.post("/runs", json=_spec("run-pinned", catalogue_versions={CATALOGUE: 1}))

    assert newest.json()["catalogue_versions"] == {CATALOGUE: 2}
    assert pinned.json()["catalogue_versions"] == {CATALOGUE: 1}


def test_a_version_nobody_published_is_refused_before_anything_is_written(
    client: TestClient, store: MemoryObjectStore, dispatcher: RecordingDispatcher
) -> None:
    response = client.post("/runs", json=_spec("run-bad-pin", catalogue_versions={CATALOGUE: 7}))

    assert response.status_code == 400
    assert "version 7" in response.json()["detail"]
    assert not store.exists(layout.spec("run-bad-pin"))
    assert dispatcher.launched == []


def test_a_pin_for_a_catalogue_the_run_does_not_name_is_not_frozen(
    client: TestClient, store: MemoryObjectStore
) -> None:
    response = client.post(
        "/runs", json=_spec("run-stray", catalogue_versions={CATALOGUE: 1, "somebody-else": 9})
    )
    assert response.status_code == 202, response.text
    frozen = RunSpec.model_validate_json(store.get(layout.spec("run-stray")))
    assert frozen.catalogue_versions == {CATALOGUE: 1}


def test_every_secret_the_spec_names_reaches_the_launch_by_reference_and_nothing_else(
    client: TestClient, dispatcher: RecordingDispatcher, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("JUDGE_KEY", "j")
    monkeypatch.setenv("GEN_KEY", "g")
    monkeypatch.setenv("UNRELATED_KEY", "another run's business")

    response = client.post(
        "/runs",
        json=_spec(
            "run-secrets",
            judge={"model": "a/b", "provider": "openrouter", "secret_ref": "JUDGE_KEY"},
            generator={"model": "a/c", "provider": "openrouter", "secret_ref": "GEN_KEY"},
            context={"language": "en", "domain": "an assistant"},
        ),
    )

    assert response.status_code == 202, response.text
    [(_, refs)] = dispatcher.launched
    assert refs == ("TARGET_KEY", "JUDGE_KEY", "GEN_KEY")


def test_the_brain_registry_credential_travels_when_the_deployment_names_one(
    client: TestClient, dispatcher: RecordingDispatcher, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("REGISTRY_CREDS", "u:t")
    from redteam_settings.config import load

    monkeypatch.setattr(
        deps,
        "settings",
        lambda: load().model_copy(update={"brain_registry_secret_ref": "REGISTRY_CREDS"}),
    )

    response = client.post("/runs", json=_spec("run-registry"))

    assert response.status_code == 202, response.text
    [(_, refs)] = dispatcher.launched
    assert refs == ("TARGET_KEY", "REGISTRY_CREDS")


def test_a_secret_nothing_can_resolve_is_refused_before_the_spec_is_frozen(
    client: TestClient,
    store: MemoryObjectStore,
    dispatcher: RecordingDispatcher,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("NOBODY_SET_THIS", raising=False)

    response = client.post(
        "/runs",
        json=_spec(
            "run-typo-ref",
            judge={"model": "a/b", "provider": "openrouter", "secret_ref": "NOBODY_SET_THIS"},
        ),
    )

    assert response.status_code == 400
    assert "NOBODY_SET_THIS" in response.json()["detail"]
    assert not store.exists(layout.spec("run-typo-ref"))
    assert dispatcher.launched == []


def test_on_a_cluster_the_gate_does_not_resolve_what_the_platform_holds(
    client: TestClient, dispatcher: RecordingDispatcher, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The kubernetes backend hands the runner references into the platform's Secret, which this
    process may not hold; refusing a run for a key the cluster has would be wrong."""
    monkeypatch.delenv("NOBODY_SET_THIS", raising=False)
    monkeypatch.setattr(deps, "hands_values", lambda: False)

    response = client.post(
        "/runs",
        json=_spec(
            "run-cluster",
            judge={"model": "a/b", "provider": "openrouter", "secret_ref": "NOBODY_SET_THIS"},
        ),
    )

    assert response.status_code == 202, response.text
    assert dispatcher.launched == [("run-cluster", ("TARGET_KEY", "NOBODY_SET_THIS"))]


def test_an_attacker_the_catalogue_conducts_through_and_the_spec_does_not_bind_is_a_400(
    client: TestClient, store: MemoryObjectStore, dispatcher: RecordingDispatcher
) -> None:
    response = client.post("/runs", json=_spec("run-unbound", attackers={}))

    assert response.status_code == 400
    assert "crescendo" in response.json()["detail"]
    assert not store.exists(layout.spec("run-unbound"))
    assert dispatcher.launched == []


def test_a_grounded_run_over_the_seed_is_not_asked_to_bind_the_standing_half_s_attacker(
    client: TestClient,
) -> None:
    """With a brain, the seed generates its premise-bearing half, none of which is conducted; the
    attacker the standing half names is inert and need not be bound."""
    response = client.post(
        "/runs",
        json=_spec(
            "run-grounded",
            kb_ref={"registry": "ghcr.io", "repository": "acme/kb", "digest": "sha256:" + "b" * 64},
            attackers={},
        ),
    )
    assert response.status_code == 202, response.text


def test_a_selection_that_attacks_nothing_is_refused(
    client: TestClient, store: MemoryObjectStore
) -> None:
    response = client.post("/runs", json=_spec("run-empty", plugins=["nothing-like-this"]))
    assert response.status_code == 400
    assert "select no strategy" in response.json()["detail"]
    assert not store.exists(layout.spec("run-empty"))


def test_a_model_driven_construction_without_a_generator_is_refused_at_the_gate(
    client: TestClient, store: MemoryObjectStore
) -> None:
    """`assistant-invented-siblings` names `contextual_sibling`; a grounded run over it with no
    generator and no context is refused before a brain is pulled."""
    bundle = load_bundle(BASELINE.parent / "assistant-invented-siblings")
    assets.publish(
        store,
        "siblings",
        bundle.catalogue,
        bundle.contract,
        *declared_engines(bundle.entity_kinds),
        needs_base=sorted(assets.needs_a_base(bundle.catalogue, bundle.needs_base)),
        delivery=bundle.delivery,
    )

    response = client.post(
        "/runs",
        json=_spec(
            "run-siblings",
            catalogues=["siblings"],
            kb_ref={"registry": "ghcr.io", "repository": "acme/kb", "digest": "sha256:" + "b" * 64},
            attackers={},
        ),
    )

    assert response.status_code == 400
    assert "contextual_sibling" in response.json()["detail"]


def test_catalogues_that_disagree_on_the_contract_are_refused_as_unprocessable(
    client: TestClient, store: MemoryObjectStore, dispatcher: RecordingDispatcher
) -> None:
    bundle = load_bundle(BASELINE)
    reweighted = bundle.contract
    first, second, *rest = reweighted.principles
    from redteam_contracts.contract import ContractSpec, PrincipleSpec

    other = ContractSpec(
        version=reweighted.version,
        positive_tokens=reweighted.positive_tokens,
        negative_tokens=reweighted.negative_tokens,
        principles=(
            PrincipleSpec(first.id, round(first.weight + 0.02, 4), first.rubric),
            PrincipleSpec(second.id, round(second.weight - 0.02, 4), second.rubric),
            *rest,
        ),
    )
    assets.publish(
        store,
        "reweighted",
        bundle.catalogue,
        other,
        *declared_engines(bundle.entity_kinds),
        needs_base=sorted(assets.needs_a_base(bundle.catalogue, bundle.needs_base)),
        delivery=bundle.delivery,
    )

    response = client.post(
        "/runs", json=_spec("run-disagree", catalogues=[CATALOGUE, "reweighted"])
    )

    assert response.status_code == 422
    assert "different contracts" in response.json()["detail"]
    assert dispatcher.launched == []


def test_the_same_request_again_is_a_202_and_a_relaunch(
    client: TestClient, dispatcher: RecordingDispatcher
) -> None:
    """The consumer lost the first answer and sends the same thing: one frozen spec, and a runner
    launched again, because the API may have died between freezing and launching."""
    first = client.post("/runs", json=_spec("run-retry"))
    again = client.post("/runs", json=_spec("run-retry"))

    assert first.status_code == 202 and again.status_code == 202
    assert again.json() == first.json()
    assert [run_id for run_id, _ in dispatcher.launched] == ["run-retry", "run-retry"]


def test_a_different_request_under_a_frozen_id_is_a_409_naming_the_fields(
    client: TestClient, store: MemoryObjectStore, dispatcher: RecordingDispatcher
) -> None:
    assert client.post("/runs", json=_spec("run-corrected")).status_code == 202
    corrected = _spec("run-corrected", replicas=3)
    corrected["connector"]["endpoint"] = "https://other.example/api"

    conflict = client.post("/runs", json=corrected)

    assert conflict.status_code == 409
    detail = conflict.json()["detail"]
    assert "connector" in detail and "replicas" in detail
    frozen = RunSpec.model_validate_json(store.get(layout.spec("run-corrected")))
    assert frozen.replicas == 1 and frozen.connector.endpoint == "https://runtime.example/api"
    assert [run_id for run_id, _ in dispatcher.launched] == ["run-corrected"], "nothing relaunched"


def test_removing_a_nested_value_on_the_retry_is_a_conflict(
    client: TestClient, dispatcher: RecordingDispatcher
) -> None:
    original = _spec("run-removal")
    assert client.post("/runs", json=original).status_code == 202

    emptied = dict(original)
    emptied["connector"] = {**original["connector"], "options": {}}
    conflict = client.post("/runs", json=emptied)

    assert conflict.status_code == 409 and "connector" in conflict.json()["detail"]
    assert [run_id for run_id, _ in dispatcher.launched] == ["run-removal"]


def test_a_runner_already_attacking_is_a_202_that_says_nothing_was_launched(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    class _Refusing:
        def launch(self, run_id: str, **_: Any) -> JobHandle:
            raise AlreadyRunning(f"a Job named redteam-run-{run_id} already exists")

        def status(self, run_id: str) -> JobState:
            return JobState.RUNNING

    monkeypatch.setattr(deps, "dispatcher", lambda: _Refusing())

    response = client.post("/runs", json=_spec("run-still-attacking"))

    assert response.status_code == 202, response.text
    assert response.json()["launched"] is False


@pytest.mark.parametrize("outside", ["Run_1", "run.1", "RUN-1", "-run", "a" * 51])
def test_a_run_id_outside_the_rule_is_refused_before_anything_is_frozen(
    client: TestClient, dispatcher: RecordingDispatcher, outside: str
) -> None:
    response = client.post("/runs", json=_spec(outside))
    assert response.status_code == 400, response.text
    assert "does not follow the rule" in response.json()["detail"]
    assert dispatcher.launched == []


def test_post_runs_takes_a_body_and_no_query_parameters() -> None:
    assert "parameters" not in app.openapi()["paths"]["/runs"]["post"]


def test_validate_answers_what_would_be_frozen_and_writes_nothing(
    client: TestClient, store: MemoryObjectStore, dispatcher: RecordingDispatcher
) -> None:
    response = client.post("/runs:validate", json=_spec("run-dry"))

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["catalogue_versions"] == {CATALOGUE: 1}
    assert body["contract_digest"].startswith("sha256:")
    assert body["secret_refs"] == ["TARGET_KEY"]
    assert not store.exists(layout.spec("run-dry"))
    assert dispatcher.launched == []

    refused = client.post("/runs:validate", json=_spec("run-dry", attackers={}))
    assert refused.status_code == 400


def test_the_status_reads_the_store_and_the_platform_and_a_stalled_run_can_be_resumed(
    client: TestClient, store: MemoryObjectStore, dispatcher: RecordingDispatcher
) -> None:
    assert client.post("/runs", json=_spec("run-status")).status_code == 202

    accepted = client.get("/runs/run-status").json()
    assert accepted["phase"] == "accepted" and accepted["runner"] == "running"
    assert accepted["planned"] is None and not accepted["stalled"]

    # The runner pinned a probe set of four and closed one unit, then the platform lost it.
    store.put(layout.attempt("run-status", "20260910T170000.000000Z-aaaaaa"), b"{}")
    store.put(layout.probes("run-status"), json.dumps({"digest": "d" * 64, "count": 4}).encode())
    store.put(layout.trace("run-status", "a" * 32, 0), b"")
    dispatcher.states["run-status"] = JobState.UNKNOWN

    stalled = client.get("/runs/run-status").json()
    assert stalled["phase"] == "attacking" and stalled["runner"] == "unknown"
    assert stalled["stalled"] is True
    assert (stalled["planned"], stalled["closed"], stalled["pending"]) == (4, 1, 3)

    resumed = client.post("/runs/run-status:resume")
    assert resumed.status_code == 202, resumed.text
    assert resumed.json()["launched"] is True
    assert [run_id for run_id, _ in dispatcher.launched] == ["run-status", "run-status"]
    assert client.get("/runs/run-status").json()["stalled"] is False

    assert client.get("/runs/run-status/result").status_code == 404
    store.put(layout.manifest("run-status"), json.dumps({"phase": "complete"}).encode())
    assert client.get("/runs/run-status").json()["phase"] == "complete"
    assert client.get("/runs/run-status/result").json() == {"phase": "complete"}
    assert client.post("/runs/run-status:resume").status_code == 409, "closed runs are not resumed"


def test_an_unknown_run_is_a_404_everywhere(client: TestClient) -> None:
    assert client.get("/runs/nobody").status_code == 404
    assert client.get("/runs/nobody/result").status_code == 404
    assert client.post("/runs/nobody:resume").status_code == 404


def test_a_platform_that_refuses_to_launch_is_a_503(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from redteam_dispatch import DispatchError

    class _Down:
        def launch(self, run_id: str, **_: Any) -> JobHandle:
            raise DispatchError("the daemon is not there")

        def status(self, run_id: str) -> JobState:
            return JobState.UNKNOWN

    monkeypatch.setattr(deps, "dispatcher", lambda: _Down())

    response = client.post("/runs", json=_spec("run-no-platform"))

    assert response.status_code == 503
    assert "daemon" in response.json()["detail"]


def test_healthz(client: TestClient) -> None:
    assert client.get("/healthz").json() == {"status": "ok"}
