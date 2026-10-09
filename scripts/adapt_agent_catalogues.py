"""Convert legacy four-file agent catalogue bundles into publishable v2 documents."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, cast
from zipfile import ZipFile

from redteam_catalogue.assets import check_document
from redteam_contracts.catalogue import CatalogueDocument


def adapt(archive: ZipFile, name: str) -> CatalogueDocument:
    prefix = f"agent-catalogues/{name}/"

    def read(filename: str) -> dict[str, Any]:
        return cast(dict[str, Any], json.loads(archive.read(prefix + filename)))

    catalogue = read("catalogue.json")
    contract = read("contract.json")
    needs_base = set(read("grounding.json")["needs_base"])
    delivery = read("delivery.json")["delivery"]
    strategy_ids = {strategy["id"] for strategy in catalogue["strategies"]}
    if unknown := (needs_base | delivery.keys()) - strategy_ids:
        raise ValueError(f"{name}: sidecars name unknown strategies: {sorted(unknown)}")

    strategies = []
    for source in catalogue["strategies"]:
        strategy = {key: value for key, value in source.items() if key != "phrasing_hint"}
        strategy["requires_brain"] = source["id"] in needs_base
        if source["id"] in delivery:
            rule = delivery[source["id"]]
            if rule["turns"] != "many":
                raise ValueError(f"{name}: unsupported delivery for {source['id']}")
            strategy["interaction"] = {
                "mode": "adaptive_multi_turn",
                "opening": source["phrasing_hint"],
                "attacker": rule["attacker"],
                "max_turns": rule["max_turns"],
            }
        else:
            strategy["interaction"] = {
                "mode": "single_turn",
                "prompt": source["phrasing_hint"],
            }
        strategies.append(strategy)

    document = CatalogueDocument.model_validate(
        {
            "schema_version": 2,
            "name": name,
            "contract": contract,
            "plugins": catalogue["plugins"],
            "strategies": strategies,
        }
    )
    check_document(document)
    return document


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("output_dir", type=Path)
    args = parser.parse_args()

    names = (
        "agent-persona-manipulation",
        "agent-scope-resistance",
        "agent-sycophancy",
    )
    args.output_dir.mkdir(parents=True, exist_ok=True)
    with ZipFile(args.archive) as archive:
        for name in names:
            document = adapt(archive, name)
            output = args.output_dir / f"{name}.json"
            output.write_text(
                json.dumps(document.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n"
            )
            print(
                f"{output}: {len(document.plugins)} plugins, {len(document.strategies)} strategies"
            )


if __name__ == "__main__":
    main()
