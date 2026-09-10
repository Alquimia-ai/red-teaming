"""Publishing and validating bundles and priors, and reading a probe set back."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from redteam_store import layout
from redteam_store.memory import MemoryObjectStore

ROOT = Path(__file__).resolve().parents[3]
BASELINE = ROOT / "deploy" / "seed" / "catalogues" / "assistant-baseline"
CATALOGUE = "assistant-baseline"
SIBLINGS = BASELINE.parent / "assistant-invented-siblings"


def _bundle(directory: Path, name: str, **overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "name": name,
        "catalogue": json.loads((directory / "catalogue.json").read_text()),
        "contract": json.loads((directory / "contract.json").read_text()),
    }
    grounding = directory / "grounding.json"
    if grounding.is_file():
        body["needs_base"] = json.loads(grounding.read_text())["needs_base"]
    delivery = directory / "delivery.json"
    if delivery.is_file():
        body["delivery"] = json.loads(delivery.read_text())
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
    assert store.exists(layout.catalogue_contract("siblings", 1))

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
    assert "ask-about-invented-sibling" in body["needs_base"] or body["needs_base"]
    assert not store.list_prefix(layout.catalogue_prefix("siblings"))


def test_a_malformed_catalogue_is_a_400_and_a_failed_check_a_422(
    client: TestClient, store: MemoryObjectStore
) -> None:
    malformed = client.post(
        "/catalogues", json=_bundle(BASELINE, "broken", catalogue={"plugins": "nope"})
    )
    assert malformed.status_code == 400 and "catalogue.json" in malformed.json()["detail"]

    bad_contract = client.post(
        "/catalogues", json=_bundle(BASELINE, "broken", contract={"version": "v1"})
    )
    assert bad_contract.status_code == 400 and "contract.json" in bad_contract.json()["detail"]

    dangling = _bundle(BASELINE, "broken")
    dangling["catalogue"]["plugins"][0]["principle"] = "no_such_principle"
    refused = client.post("/catalogues", json=dangling)
    assert refused.status_code == 422
    refused_check = client.post("/catalogues:validate", json=dangling)
    assert refused_check.status_code == 422

    assert not store.list_prefix(layout.catalogue_prefix("broken"))


def test_the_grounding_a_phrasing_implies_is_derived_and_the_sidecar_adds_to_it(
    client: TestClient, store: MemoryObjectStore
) -> None:
    """A phrasing carrying `{premise}` says it needs a base; the API reads that off the catalogue
    the way an author would, so `needs_base` only has to name the slotless strategies that want a
    premise appended. What was derived is answered back, so the author sees what was declared."""
    derived = _bundle(BASELINE, "derived", needs_base=[])

    checked = client.post("/catalogues:validate", json=derived).json()
    published = client.post("/catalogues", json=derived)

    assert "ask-about-fake-product" in checked["needs_base"]
    assert "ask-identity" not in checked["needs_base"]
    assert published.status_code == 201, published.text
    assert store.exists(layout.catalogue_grounding("derived", 1))


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
