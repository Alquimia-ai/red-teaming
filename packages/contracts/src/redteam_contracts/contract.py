"""The behavioural contract, as data.

The contract is the criterion: every response the profiler and the exploiter collect is graded
against its principles, so which contract graded a run is part of what that run measured. It
is embedded in the schema-v2 catalogue document because its plugins name these principles. A
plugin charging a principle the document does not carry is a catalogue that cannot be graded.

Deliberately free of gaussia: parsing the declaration needs yaml and nothing else, while *binding* a
grader to it needs the library. The catalogue package does the binding; this module only says what
a well-formed contract is.

A weight is a **severity**, not a confidence: the violation score of one exchange is the weighted
sum of the grades, so a response breaking only the lightest principle scores low on purpose. The
weights sum to one, which gaussia enforces to within `1e-9` and this parser enforces first.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

KNOWN_KEYS = frozenset({"version", "verdict", "principles"})
KNOWN_VERDICT_KEYS = frozenset({"positive", "negative"})
KNOWN_PRINCIPLE_KEYS = frozenset({"id", "weight", "rubric"})
"""Everything a contract may say. Anything else is refused by name: a schema that drops an unknown
key in silence turns a declaration into nothing, and a `weigth` with a typo that quietly reads as
absent is exactly how a contract stops meaning what its author wrote."""

WEIGHT_TOLERANCE = 1e-9


@dataclass(frozen=True)
class PrincipleSpec:
    """One principle as the file declares it, before a grader is bound to it."""

    id: str
    weight: float
    rubric: str
    """Handed to the judge unmodified. One rule, stated in the positive, with the boundary named
    and the question explicit."""


@dataclass(frozen=True)
class ContractSpec:
    """The declarative side: what the assistant is held to, and in what wording."""

    version: str
    """The author's label for this revision. Reported rather than trusted: the store's version
    number is what a run freezes."""

    positive_tokens: tuple[str, ...]
    """What the judge says when the principle is violated. Matched against the verdict token, so
    spelled as tokens -- with and without a leading space -- rather than as a word."""

    negative_tokens: tuple[str, ...]
    principles: tuple[PrincipleSpec, ...]

    @property
    def principle_ids(self) -> frozenset[str]:
        return frozenset(p.id for p in self.principles)

    def principle(self, identifier: str) -> PrincipleSpec | None:
        return next((p for p in self.principles if p.id == identifier), None)


def as_raw(spec: ContractSpec) -> dict[str, Any]:
    """The declaration as data again: what is embedded into the catalogue document.

    From the parsed spec rather than from the author's bytes, so two files that declare the same
    contract -- one in YAML, one in JSON, one with a rubric wrapped differently -- land as the same
    bytes and answer with the same digest.
    """
    return {
        "version": spec.version,
        "verdict": {"positive": list(spec.positive_tokens), "negative": list(spec.negative_tokens)},
        "principles": [
            {"id": p.id, "weight": p.weight, "rubric": p.rubric} for p in spec.principles
        ],
    }


def load_contract_spec(path: Path) -> ContractSpec:
    """The contract in a file. For a fixture or a seed; a run reads its own from the store."""
    return parse_contract_spec(path.read_text())


def parse_contract_spec(source: str | bytes) -> ContractSpec:
    """The contract as it was declared.

    `yaml.safe_load` reads JSON too, YAML being a superset of it, so one parser serves the authored
    file and the canonical JSON the store holds without either side having to say which it is.

    Raises:
        ValueError: The declaration is not a contract: a key nothing reads, no principles, a blank
            or duplicate id, an empty rubric, weights that do not sum to one, or a verdict with no
            tokens on one side.
    """
    raw = yaml.safe_load(source)
    if not isinstance(raw, Mapping):
        raise ValueError(f"a contract is a mapping, not {type(raw).__name__}")
    _refuse_unknown("contract", raw, KNOWN_KEYS)
    for required in ("version", "verdict", "principles"):
        if required not in raw:
            raise ValueError(f"a contract declares {required!r}; this one does not")

    verdict = raw["verdict"]
    if not isinstance(verdict, Mapping):
        raise ValueError("`verdict` is a mapping of positive and negative tokens")
    _refuse_unknown("verdict", verdict, KNOWN_VERDICT_KEYS)
    positive = _tokens("positive", verdict.get("positive"))
    negative = _tokens("negative", verdict.get("negative"))

    declared = raw["principles"]
    if not isinstance(declared, list) or not declared:
        raise ValueError("a contract carries at least one principle")
    principles = tuple(_principle(p) for p in declared)
    _check_ids_are_unique(principles)
    _check_weights(principles)
    return ContractSpec(
        version=str(raw["version"]),
        positive_tokens=positive,
        negative_tokens=negative,
        principles=principles,
    )


def _refuse_unknown(where: str, declared: Mapping[str, Any], known: frozenset[str]) -> None:
    unknown = sorted(set(map(str, declared)) - known)
    if unknown:
        raise ValueError(
            f"{where} carries keys this contract format does not know: {unknown}. A key nothing "
            f"reads would declare nothing; the fields are {sorted(known)}"
        )


def _tokens(side: str, raw: Any) -> tuple[str, ...]:
    if not isinstance(raw, list) or not raw or not all(isinstance(t, str) and t for t in raw):
        raise ValueError(f"verdict.{side} is a non-empty list of tokens")
    return tuple(raw)


def _principle(raw: Any) -> PrincipleSpec:
    if not isinstance(raw, Mapping):
        raise ValueError(f"a principle is a mapping, not {type(raw).__name__}")
    _refuse_unknown("a principle", raw, KNOWN_PRINCIPLE_KEYS)
    identifier = str(raw.get("id", "")).strip()
    if not identifier:
        raise ValueError("a principle carries a non-blank id")
    try:
        weight = float(raw["weight"])
    except (KeyError, TypeError, ValueError) as bad:
        raise ValueError(f"principle {identifier!r} declares no numeric weight") from bad
    if weight <= 0:
        raise ValueError(f"principle {identifier!r} declares weight {weight}; a severity is > 0")
    rubric = " ".join(str(raw.get("rubric", "")).split())
    if not rubric:
        raise ValueError(f"principle {identifier!r} carries an empty rubric")
    return PrincipleSpec(id=identifier, weight=weight, rubric=rubric)


def _check_ids_are_unique(principles: tuple[PrincipleSpec, ...]) -> None:
    seen: set[str] = set()
    for principle in principles:
        if principle.id in seen:
            raise ValueError(f"principle {principle.id!r} is declared twice")
        seen.add(principle.id)


def _check_weights(principles: tuple[PrincipleSpec, ...]) -> None:
    total = sum(p.weight for p in principles)
    if abs(total - 1.0) > WEIGHT_TOLERANCE:
        raise ValueError(
            f"the principle weights are severities and have to sum to 1.0; they sum to {total}"
        )
