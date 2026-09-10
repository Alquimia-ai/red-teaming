"""A bundle directory becomes the API's request body without the probe library."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from redteam_cli.bundle import BundleIncomplete, read_bundle, read_phrasings, read_spec

ROOT = Path(__file__).resolve().parents[3]
BASELINE = ROOT / "deploy" / "seed" / "catalogues" / "assistant-baseline"


def test_the_seed_bundle_reads_as_the_body_the_api_takes() -> None:
    body = read_bundle(BASELINE, "baseline")

    assert body["name"] == "baseline"
    assert {p["id"] for p in body["catalogue"]["plugins"]} >= {"invented-entity"}
    assert body["contract"]["version"] == "v1"
    assert len(body["contract"]["principles"]) == 7
    assert "ask-about-fake-product" in body["needs_base"]
    assert body["delivery"]["delivery"]["escalate-system-prompt"]["attacker"] == "crescendo"


def test_a_yaml_contract_travels_as_the_same_data(tmp_path: Path) -> None:
    (tmp_path / "catalogue.json").write_text(json.dumps({"plugins": [], "strategies": []}))
    (tmp_path / "contract.yaml").write_text(
        "version: v9\nverdict: {positive: ['YES'], negative: ['NO']}\n"
        "principles:\n  - {id: p, weight: 1.0, rubric: r}\n"
    )

    body = read_bundle(tmp_path, "yaml")

    assert body["contract"] == {
        "version": "v9",
        "verdict": {"positive": ["YES"], "negative": ["NO"]},
        "principles": [{"id": "p", "weight": 1.0, "rubric": "r"}],
    }
    assert "needs_base" not in body and "delivery" not in body


def test_a_bundle_missing_a_file_it_cannot_be_published_without_says_which(
    tmp_path: Path,
) -> None:
    with pytest.raises(BundleIncomplete, match=r"catalogue\.json"):
        read_bundle(tmp_path, "x")
    (tmp_path / "catalogue.json").write_text("{}")
    with pytest.raises(BundleIncomplete, match="contract"):
        read_bundle(tmp_path, "x")


def test_a_spec_reads_from_json_or_yaml_and_a_prior_from_json_or_lines(tmp_path: Path) -> None:
    (tmp_path / "spec.json").write_text('{"run_id": "r"}')
    (tmp_path / "spec.yaml").write_text("run_id: r\nreplicas: 2\n")
    (tmp_path / "prior.json").write_text('["a", "b"]')
    (tmp_path / "prior.txt").write_text("a\n\n b \n")

    assert read_spec(tmp_path / "spec.json") == {"run_id": "r"}
    assert read_spec(tmp_path / "spec.yaml") == {"run_id": "r", "replicas": 2}
    assert read_phrasings(tmp_path / "prior.json") == ["a", "b"]
    assert read_phrasings(tmp_path / "prior.txt") == ["a", "b"]
    (tmp_path / "list.yaml").write_text("- a\n")
    with pytest.raises(ValueError, match="mapping"):
        read_spec(tmp_path / "list.yaml")
