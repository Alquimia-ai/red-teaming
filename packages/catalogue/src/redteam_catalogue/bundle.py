"""A catalogue bundle on disk: the directory an author writes and the CLI publishes.

Four files, one required beside the catalogue: `catalogue.json` (plugins and strategies),
`contract.json` or `contract.yaml` (the principles the plugins charge -- required, because a
catalogue whose plugins name principles nobody declared cannot be graded), `grounding.json` (which
strategies need a knowledge base beyond what their phrasing says) and `delivery.json` (which
strategies are delivered as a conversation an attacker steers).

The bundle is published as **one** version. Sidecars land before the catalogue's commit key, so a
half-written publication is never exposed as a complete version.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from gaussia.schemas.roastme import Catalogue

from redteam_contracts.contract import ContractSpec, parse_contract_spec
from redteam_store import grounding as grounding_store

CATALOGUE_FILE = "catalogue.json"
CONTRACT_FILES = ("contract.json", "contract.yaml", "contract.yml")
GROUNDING_FILE = "grounding.json"
DELIVERY_FILE = "delivery.json"


class BundleIncomplete(FileNotFoundError):
    """A bundle directory missing a file it cannot be published without."""


@dataclass(frozen=True)
class Bundle:
    """What a bundle directory declares, parsed and shape-checked but not yet validated together."""

    catalogue: Catalogue
    contract: ContractSpec
    needs_base: frozenset[str]
    """The grounding sidecar as declared, or empty when the directory carries none."""

    delivery: dict[str, Any] | None
    """The delivery sidecar's raw block, or None when the directory carries none. Left raw so the
    publisher normalises and refuses it with the same rules the API applies."""

    @property
    def entity_kinds(self) -> tuple[str, ...]:
        return tuple(sorted({strategy.entity_kind for strategy in self.catalogue.strategies}))


def load_bundle(directory: Path) -> Bundle:
    """Read a bundle directory.

    Raises:
        BundleIncomplete: `catalogue.json` or the contract file is missing.
        ValueError: A file does not parse as what it must be.
    """
    catalogue_path = directory / CATALOGUE_FILE
    if not catalogue_path.is_file():
        raise BundleIncomplete(f"{directory} carries no {CATALOGUE_FILE}")
    contract_path = next(
        (directory / name for name in CONTRACT_FILES if (directory / name).is_file()), None
    )
    if contract_path is None:
        raise BundleIncomplete(
            f"{directory} carries no contract ({' or '.join(CONTRACT_FILES)}); a catalogue whose "
            f"plugins charge principles nobody declared cannot be graded"
        )
    catalogue = Catalogue.model_validate(json.loads(catalogue_path.read_text()))
    contract = parse_contract_spec(contract_path.read_text())

    needs_base: frozenset[str] = frozenset()
    grounding_path = directory / GROUNDING_FILE
    if grounding_path.is_file():
        needs_base = grounding_store.normalise(json.loads(grounding_path.read_text()))

    delivery: dict[str, Any] | None = None
    delivery_path = directory / DELIVERY_FILE
    if delivery_path.is_file():
        raw = json.loads(delivery_path.read_text())
        if not isinstance(raw, dict):
            raise ValueError(f"{delivery_path} must hold a mapping")
        delivery = raw

    return Bundle(catalogue=catalogue, contract=contract, needs_base=needs_base, delivery=delivery)
