"""A catalogue bundle directory as the API's request body.

The same four files the catalogue package reads, read here without it: the command line carries
the contracts package and nothing that needs the probe library. The contract may be written as YAML
and travels as data; the catalogue, grounding and delivery files travel as the JSON they are, and
the API is what validates them.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from redteam_contracts.contract import as_raw, load_contract_spec

CATALOGUE_FILE = "catalogue.json"
CONTRACT_FILES = ("contract.json", "contract.yaml", "contract.yml")
GROUNDING_FILE = "grounding.json"
DELIVERY_FILE = "delivery.json"


class BundleIncomplete(FileNotFoundError):
    pass


def read_bundle(directory: Path, name: str) -> dict[str, Any]:
    """The request body `POST /catalogues` takes, from the files an author writes.

    Raises:
        BundleIncomplete: `catalogue.json` or the contract is missing.
        ValueError: A file does not parse as what it must be.
    """
    catalogue_path = directory / CATALOGUE_FILE
    if not catalogue_path.is_file():
        raise BundleIncomplete(f"{directory} carries no {CATALOGUE_FILE}")
    contract_path = next(
        (
            directory / candidate
            for candidate in CONTRACT_FILES
            if (directory / candidate).is_file()
        ),
        None,
    )
    if contract_path is None:
        raise BundleIncomplete(
            f"{directory} carries no contract ({' or '.join(CONTRACT_FILES)}); a catalogue whose "
            f"plugins charge principles nobody declared cannot be graded"
        )
    body: dict[str, Any] = {
        "name": name,
        "catalogue": json.loads(catalogue_path.read_text()),
        "contract": as_raw(load_contract_spec(contract_path)),
    }
    grounding = directory / GROUNDING_FILE
    if grounding.is_file():
        raw = json.loads(grounding.read_text())
        body["needs_base"] = list(raw["needs_base"] if isinstance(raw, dict) else raw)
    delivery = directory / DELIVERY_FILE
    if delivery.is_file():
        body["delivery"] = json.loads(delivery.read_text())
    return body


def read_spec(path: Path) -> dict[str, Any]:
    """A run spec as the operator wrote it: JSON, or YAML for the same content."""
    import yaml

    loaded = yaml.safe_load(path.read_text())
    if not isinstance(loaded, dict):
        raise ValueError(f"{path} does not hold a run spec (a mapping)")
    return {str(k): v for k, v in loaded.items()}


def read_phrasings(path: Path) -> list[str]:
    """A prior: a JSON list, or one phrasing per line."""
    text = path.read_text()
    if path.suffix == ".json":
        loaded = json.loads(text)
        if isinstance(loaded, dict):
            loaded = loaded.get("phrasings", loaded.get("prior"))
        if not isinstance(loaded, list):
            raise ValueError(f"{path} does not hold a list of phrasings")
        return [str(item) for item in loaded]
    return [line.strip() for line in text.splitlines() if line.strip()]
