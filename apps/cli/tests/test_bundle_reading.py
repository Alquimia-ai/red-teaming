"""A catalogue file becomes the exact API request body."""

from __future__ import annotations

from pathlib import Path

import pytest

from redteam_cli.bundle import BundleIncomplete, read_bundle, read_phrasings, read_spec

ROOT = Path(__file__).resolve().parents[3]
BASELINE = ROOT / "deploy" / "seed" / "catalogues" / "assistant-baseline.json"


def test_the_seed_bundle_reads_as_the_body_the_api_takes() -> None:
    body = read_bundle(BASELINE)

    assert body["schema_version"] == 2
    assert body["name"] == "assistant-baseline"
    assert {p["id"] for p in body["plugins"]} >= {"invented-entity"}
    assert body["contract"]["version"] == "v1"
    assert len(body["contract"]["principles"]) == 7
    strategies = {strategy["id"]: strategy for strategy in body["strategies"]}
    assert strategies["ask-about-fake-product"]["requires_brain"] is True
    assert strategies["escalate-system-prompt"]["interaction"]["attacker"] == "crescendo"


def test_a_missing_catalogue_file_is_named(tmp_path: Path) -> None:
    with pytest.raises(BundleIncomplete, match="YAML or JSON"):
        read_bundle(tmp_path / "missing.yaml")


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
