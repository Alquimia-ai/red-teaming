"""Binding a grader to the behavioural contract.

The declarative side lives in `redteam_contracts.contract`; this is the half that needs gaussia.
"""

from __future__ import annotations

from typing import Any

from gaussia.core.grader import Grader
from gaussia.schemas.roastme import BehavioralContract, Principle, PrincipleGrade

from redteam_contracts.contract import ContractSpec

__all__ = ["DeclaredGrader", "build_contract", "validation_contract"]


class DeclaredGrader(Grader):  # type: ignore[misc]  # gaussia ships no stubs
    """A grader named so a contract can be validated, and never allowed to grade.

    Catalogue validation reads the principles' identifiers and weights; it never grades with them.
    Binding a real judge to answer a question about identifiers would make publishing a bundle cost
    what running one costs. `grade` refuses rather than returning a score, because a placeholder
    that grades is exactly how a fixture's number ends up in a real run.
    """

    def grade(
        self,
        query: str,
        response: str,
        principle: Principle,
        meta: dict[str, Any] | None = None,
    ) -> PrincipleGrade:
        raise NotImplementedError(
            f"the contract was bound for validation only; grading {principle.id!r} needs the run's "
            f"own judge, built by the engine from the spec"
        )


def build_contract(spec: ContractSpec, grader: Grader) -> BehavioralContract:
    """Bind a grader to every principle.

    One grader instance can serve several principles. What the specification fixes is that each
    principle has exactly one, so comparing graders means running the whole evaluation twice rather
    than averaging two inside a principle. The rubric travels **unmodified**: gaussia neither
    rewrites nor appends to it, so what the contract says is exactly what the model is asked.
    """
    return BehavioralContract(
        principles=[
            Principle(id=p.id, weight=p.weight, rubric=p.rubric, grader=grader)
            for p in spec.principles
        ]
    )


def validation_contract(spec: ContractSpec) -> BehavioralContract:
    """The contract as validation sees it: every principle present, none of them able to grade."""
    return build_contract(spec, DeclaredGrader())
