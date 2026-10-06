"""Publishing and validating bundles and priors, and reading a probe set back."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from redteam_catalogue.assets import load_document
from redteam_store import layout
from redteam_store.memory import MemoryObjectStore

ROOT = Path(__file__).resolve().parents[3]
BASELINE = ROOT / "deploy" / "seed" / "catalogues" / "assistant-baseline"
CATALOGUE = "assistant-baseline"
SIBLINGS = BASELINE.parent / "assistant-invented-siblings"


def _bundle(directory: Path, name: str, **overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = json.loads(directory.with_suffix(".json").read_text())
    body["name"] = name
    body.update(overrides)
    return body


def test_a_bundle_is_published_once_and_named_again(
    client: TestClient, store: MemoryObjectStore
) -> None:
    """The fixture published the baseline already, so this publish writes nothing and says so."""
    again = client.post("/catalogues", json=_bundle(BASELINE, CATALOGUE))
    assert again.status_code == 200, again.text
    assert again.json()["created"] is False and again.json()["version"] == 1

    new = client.post("/catalogues", json=_bundle(SIBLINGS, "siblings"))
    assert new.status_code == 201, new.text
    body = new.json()
    assert body["version"] == 1 and body["created"] is True
    assert body["contract_digest"].startswith("sha256:")
    assert body["principles"] == 7
    assert not store.exists(layout.catalogue_contract("siblings", 1))

    assert client.get("/catalogues").json() == {CATALOGUE: [1], "siblings": [1]}


def test_the_delivery_sidecar_is_published_with_the_version_and_reported(
    client: TestClient,
) -> None:
    body = client.post("/catalogues", json=_bundle(BASELINE, CATALOGUE)).json()
    assert body["delivered"] == ["escalate-system-prompt"]


def test_validate_runs_every_check_and_writes_nothing(
    client: TestClient, store: MemoryObjectStore
) -> None:
    response = client.post("/catalogues:validate", json=_bundle(SIBLINGS, "siblings"))

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["principles"] == 7 and body["strategies"] >= 2
    assert "ask-about-plausible-sibling" in body["requires_brain"]
    assert not store.list_prefix(layout.catalogue_prefix("siblings"))


def test_a_malformed_catalogue_is_a_400_and_a_failed_check_a_422(
    client: TestClient, store: MemoryObjectStore
) -> None:
    malformed = client.post("/catalogues", json=_bundle(BASELINE, "broken", plugins="nope"))
    assert malformed.status_code == 422

    bad_contract = client.post(
        "/catalogues", json=_bundle(BASELINE, "broken", contract={"version": "v1"})
    )
    assert bad_contract.status_code == 422

    dangling = _bundle(BASELINE, "broken")
    dangling["plugins"][0]["principle"] = "no_such_principle"
    refused = client.post("/catalogues", json=dangling)
    assert refused.status_code == 422
    refused_check = client.post("/catalogues:validate", json=dangling)
    assert refused_check.status_code == 422

    assert not store.list_prefix(layout.catalogue_prefix("broken"))


def test_brain_requirements_are_embedded_and_no_sidecar_is_written(
    client: TestClient, store: MemoryObjectStore
) -> None:
    """A phrasing carrying `{premise}` says it needs a base; the API reads that off the catalogue
    the way an author would, so `needs_base` only has to name the slotless strategies that want a
    premise appended. What was derived is answered back, so the author sees what was declared."""
    derived = _bundle(BASELINE, "derived")

    checked = client.post("/catalogues:validate", json=derived).json()
    published = client.post("/catalogues", json=derived)

    assert "ask-about-fake-product" in checked["requires_brain"]
    assert "ask-identity" not in checked["requires_brain"]
    assert published.status_code == 201, published.text
    assert not store.exists(layout.catalogue_grounding("derived", 1))


def test_priors_are_published_versioned_and_listed(client: TestClient) -> None:
    first = client.post("/priors", json={"name": "support", "phrasings": ["hola", "que cubre?"]})
    again = client.post("/priors", json={"name": "support", "phrasings": ["hola", "que cubre?"]})
    grown = client.post("/priors", json={"name": "support", "phrasings": ["hola", "otra"]})

    assert first.status_code == 201 and first.json()["size"] == 2
    assert again.status_code == 200 and again.json()["created"] is False
    assert grown.status_code == 201 and grown.json()["version"] == 2
    assert client.get("/priors").json() == {"support": [1, 2]}

    empty = client.post("/priors", json={"name": "support", "phrasings": ["  "]})
    assert empty.status_code == 422


def test_a_probe_set_is_read_by_content(client: TestClient, store: MemoryObjectStore) -> None:
    digest = "c" * 64
    store.put(layout.blob(digest), json.dumps([{"id": "p1", "query": "q?"}]).encode())

    assert client.get(f"/probes/{digest}").json() == [{"id": "p1", "query": "q?"}]
    assert client.get(f"/probes/{'d' * 64}").status_code == 404
    assert client.get("/probes/not-a-digest").status_code == 400


def test_scope_is_persisted_and_latest_library_scope_changes_without_rewriting_history(
    client: TestClient, store: MemoryObjectStore
) -> None:
    original = store.get(layout.catalogue(CATALOGUE, 1))
    scope = {"agentspace_id": "workspace", "assistant_id": "assistant"}
    document = _bundle(BASELINE, CATALOGUE, scope=scope)
    checked = client.post("/catalogues:validate", json=document)
    assert checked.status_code == 200
    assert store.get(layout.catalogue(CATALOGUE, 1)) == original
    assert client.post("/catalogues", json=document).json()["version"] == 2
    assert client.post("/catalogues", json=document).json()["created"] is False
    assert json.loads(store.get(layout.catalogue(CATALOGUE, 2)))["scope"] == scope
    assert client.get("/catalogues:library").json() == {
        CATALOGUE: {"versions": [1, 2], "scope": scope, "description": None}
    }
    assert client.get("/catalogues").json() == {CATALOGUE: [1, 2]}
    assert store.get(layout.catalogue(CATALOGUE, 1)) == original

    # Returning to global is a new version; null and omitted encode identical canonical bytes.
    restored = client.post("/catalogues", json=_bundle(BASELINE, CATALOGUE, scope=None))
    assert restored.json()["version"] == 3
    assert store.get(layout.catalogue(CATALOGUE, 3)) == original
    assert client.post("/catalogues", json=_bundle(BASELINE, CATALOGUE)).json()["created"] is False
    assert client.get("/catalogues:library").json()[CATALOGUE]["scope"] is None


def test_description_round_trips_without_changing_contract_or_previous_versions(
    client: TestClient, store: MemoryObjectStore
) -> None:
    original = store.get(layout.catalogue(CATALOGUE, 1))
    assert "description" not in json.loads(original)
    description = "Evalúa alcance y privacidad.\nIncluye controles positivos."
    document = _bundle(BASELINE, CATALOGUE, description=description)
    keys = store.list_prefix("")
    checked = client.post("/catalogues:validate", json=document)
    assert checked.status_code == 200, checked.text
    assert store.list_prefix("") == keys

    baseline = client.post("/catalogues", json=_bundle(BASELINE, CATALOGUE)).json()
    published = client.post("/catalogues", json=document)
    assert published.status_code == 201, published.text
    assert published.json()["version"] == 2
    assert published.json()["contract_digest"] == baseline["contract_digest"]
    assert published.json()["digest"] != baseline["digest"]
    assert load_document(store, CATALOGUE, 2).description == description
    assert load_document(store, CATALOGUE, 1).description is None
    assert store.get(layout.catalogue(CATALOGUE, 1)) == original
    assert client.post("/catalogues", json=document).json()["created"] is False
    assert client.get("/catalogues:library").json()[CATALOGUE] == {
        "versions": [1, 2],
        "scope": None,
        "description": description,
    }

    revised = _bundle(BASELINE, CATALOGUE, description="Sólo alcance.")
    assert client.post("/catalogues", json=revised).json()["version"] == 3
    assert client.get("/catalogues:library").json()[CATALOGUE]["description"] == "Sólo alcance."
    assert load_document(store, CATALOGUE, 2).description == description

    removed = client.post("/catalogues", json=_bundle(BASELINE, CATALOGUE, description=None))
    assert removed.json()["version"] == 4
    assert store.get(layout.catalogue(CATALOGUE, 4)) == original
    assert client.post("/catalogues", json=_bundle(BASELINE, CATALOGUE)).json()["created"] is False
    assert client.get("/catalogues:library").json()[CATALOGUE]["description"] is None
