"""One catalogue document reads back as what its author wrote."""

from __future__ import annotations

from pathlib import Path

import pytest

from redteam_catalogue.bundle import BundleIncomplete, load_bundle

ROOT = Path(__file__).resolve().parents[3]
SEEDS = ROOT / "deploy" / "seed" / "catalogues"


def test_the_baseline_seed_is_a_complete_bundle() -> None:
    bundle = load_bundle(SEEDS / "assistant-baseline.json")
    assert bundle.contract.principle_ids >= {"no_invention", "no_disclosure"}
    assert abs(sum(p.weight for p in bundle.contract.principles) - 1.0) < 1e-9
    assert "ask-about-fake-product" in bundle.needs_base
    assert bundle.delivery is not None and "escalate-system-prompt" in bundle.delivery["delivery"]
    assert bundle.entity_kinds == ("assistant", "fact", "product")


def test_the_siblings_seed_names_the_model_driven_construction() -> None:
    bundle = load_bundle(SEEDS / "assistant-invented-siblings.json")
    assert {s.transform for s in bundle.catalogue.strategies} == {"contextual_sibling", "keep_real"}
    assert bundle.delivery is None


def test_a_missing_document_is_refused_by_name(tmp_path: Path) -> None:
    with pytest.raises(BundleIncomplete, match="YAML or JSON"):
        load_bundle(tmp_path / "missing.yaml")


def test_json_content_may_be_read_from_a_yaml_file(tmp_path: Path) -> None:
    authored = tmp_path / "catalogue.yaml"
    authored.write_text((SEEDS / "assistant-invented-siblings.json").read_text())
    assert load_bundle(authored).document.schema_version == 2
