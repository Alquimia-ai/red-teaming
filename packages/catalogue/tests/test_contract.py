"""Binding a grader to the contract, and the placeholder that validates without grading."""

from __future__ import annotations

import json

import pytest
from gaussia.schemas.roastme import Principle

from redteam_catalogue.contract import DeclaredGrader, build_contract, validation_contract
from redteam_contracts.contract import parse_contract_spec

SPEC = parse_contract_spec(
    json.dumps(
        {
            "version": "v1",
            "verdict": {"positive": ["YES"], "negative": ["NO"]},
            "principles": [
                {"id": "no_invention", "weight": 0.6, "rubric": "Must not invent."},
                {"id": "no_disclosure", "weight": 0.4, "rubric": "Must not disclose."},
            ],
        }
    )
)


def test_every_principle_is_bound_with_its_rubric_unmodified() -> None:
    grader = DeclaredGrader()
    contract = build_contract(SPEC, grader)
    assert [p.id for p in contract.principles] == ["no_invention", "no_disclosure"]
    assert [p.weight for p in contract.principles] == [0.6, 0.4]
    assert contract.principles[0].rubric == "Must not invent."
    assert all(p.grader is grader for p in contract.principles)


def test_the_validation_contract_can_be_read_but_never_grades() -> None:
    contract = validation_contract(SPEC)
    principle: Principle = contract.principles[0]
    with pytest.raises(NotImplementedError, match="validation only"):
        principle.grader.grade("q", "a", principle)
