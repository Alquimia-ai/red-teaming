"""Loading and validating a catalogue.

Ten lines of wiring around what gaussia already owns. `Catalogue.model_validate` checks the shape,
and `validate_catalogue` runs the six semantic rejections against the contract and the engines
that will run -- which are, one for one, the six conformance laws of the (plugin, strategy) pair.
There is no harness to build here.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from gaussia.schemas.roastme import BehavioralContract, Catalogue


def load_catalogue(path: Path) -> Catalogue:
    """Parse and shape-check. Says nothing yet about whether it is coherent with the contract."""
    return Catalogue.model_validate(json.loads(path.read_text()))


def validate(
    catalogue: Catalogue,
    contract: BehavioralContract,
    engines: Sequence[Any],
    transforms: Sequence[Any] = (),
    twisters: Sequence[Any] = (),
) -> None:
    """Run the six semantic rejections. Raises `ValueError` naming what is wrong.

    Called before a single probe is generated, which is the point: a malformed catalogue should cost
    nothing, and certainly not a conversation against the assistant.

    `transforms` and `twisters` have to be **the same sequences the engines were built with**.
    gaussia is explicit about why: a catalogue validated against one set and generated against
    another is exactly the case where validation stops meaning anything, because a key that
    resolved during the check can be missing when it is needed.
    """
    from gaussia.generators.roastme.probes.catalogue import validate_catalogue

    validate_catalogue(catalogue, contract, engines, transforms, twisters)


def plugins_by_principle(catalogue: Catalogue) -> dict[str, list[str]]:
    """Which plugins load a violation onto which principle.

    A plugin maps to exactly one principle, and that is what decides which rubric the judge
    receives.
    """
    out: dict[str, list[str]] = {}
    for plugin in catalogue.plugins:
        out.setdefault(plugin.principle, []).append(plugin.id)
    return out


def principle_of(catalogue: Catalogue, plugin_id: str) -> str | None:
    """The principle one plugin charges, or None for an id the catalogue does not carry."""
    return next((p.principle for p in catalogue.plugins if p.id == plugin_id), None)


def controls(catalogue: Catalogue) -> tuple[str, ...]:
    """Strategies with no plugin.

    A control is sent, graded and kept in the record, and excluded from every rate. It is the honest
    denominator approached from the other side: without it, a run cannot tell "the assistant is
    careful" from "the questions were easy".
    """
    return tuple(s.id for s in catalogue.strategies if s.plugin is None)
