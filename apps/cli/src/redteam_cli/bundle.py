"""Read catalogue documents, run specs, and priors for the API."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from redteam_contracts.catalogue import CatalogueDocument


class BundleIncomplete(FileNotFoundError):
    pass


def read_bundle(path: Path) -> dict[str, Any]:
    """The one YAML or JSON document accepted by both catalogue endpoints."""
    import yaml

    if not path.is_file():
        raise BundleIncomplete(f"{path} is not a catalogue YAML or JSON file")
    document = CatalogueDocument.model_validate(yaml.safe_load(path.read_text()))
    return document.model_dump(mode="json")


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
