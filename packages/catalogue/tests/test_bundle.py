"""A bundle directory reads back as what its author wrote, or says which file is missing."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from redteam_catalogue.bundle import BundleIncomplete, load_bundle

ROOT = Path(__file__).resolve().parents[3]
SEEDS = ROOT / "deploy" / "seed" / "catalogues"


def test_the_baseline_seed_is_a_complete_bundle() -> None:
    bundle = load_bundle(SEEDS / "assistant-baseline")
    assert bundle.contract.principle_ids >= {"no_invention", "no_disclosure"}
    assert abs(sum(p.weight for p in bundle.contract.principles) - 1.0) < 1e-9
    assert "ask-about-fake-product" in bundle.needs_base
    assert bundle.delivery is not None and "escalate-system-prompt" in bundle.delivery["delivery"]
    assert bundle.entity_kinds == ("assistant", "fact", "product")


def test_the_siblings_seed_names_the_model_driven_construction() -> None:
    bundle = load_bundle(SEEDS / "assistant-invented-siblings")
    assert {s.transform for s in bundle.catalogue.strategies} == {"contextual_sibling", "keep_real"}
    assert bundle.delivery is None


def test_a_bundle_without_a_contract_is_refused_by_name(tmp_path: Path) -> None:
    (tmp_path / "catalogue.json").write_text(
        (SEEDS / "assistant-baseline" / "catalogue.json").read_text()
    )
    with pytest.raises(BundleIncomplete, match="contract"):
        load_bundle(tmp_path)


def test_a_bundle_without_a_catalogue_is_refused_by_name(tmp_path: Path) -> None:
    with pytest.raises(BundleIncomplete, match=r"catalogue\.json"):
        load_bundle(tmp_path)


def test_the_contract_may_be_yaml(tmp_path: Path) -> None:
    (tmp_path / "catalogue.json").write_text(
        (SEEDS / "assistant-invented-siblings" / "catalogue.json").read_text()
    )
    (tmp_path / "contract.yaml").write_text(
        "version: v9\n"
        "verdict:\n  positive: ['YES']\n  negative: ['NO']\n"
        "principles:\n  - id: no_invention\n    weight: 1.0\n    rubric: Must not invent.\n"
    )
    bundle = load_bundle(tmp_path)
    assert bundle.contract.version == "v9"
    assert bundle.needs_base == frozenset()


def test_a_grounding_file_that_is_not_a_list_is_refused(tmp_path: Path) -> None:
    for name in ("catalogue.json", "contract.json"):
        (tmp_path / name).write_text((SEEDS / "assistant-baseline" / name).read_text())
    (tmp_path / "grounding.json").write_text(json.dumps({"needs_base": "ask-about-fake-product"}))
    with pytest.raises(ValueError, match="needs_base"):
        load_bundle(tmp_path)
