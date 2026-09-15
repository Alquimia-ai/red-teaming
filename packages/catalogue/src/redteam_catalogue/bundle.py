"""Read a schema-v2 catalogue document; legacy directories exist only as local fixtures."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from gaussia.schemas.roastme import Catalogue

from redteam_catalogue.assets import as_catalogue, contract_of
from redteam_contracts.catalogue import (
    AdaptiveMultiTurn,
    CatalogueDocument,
    CataloguePlugin,
    CatalogueStrategy,
    ScriptedMultiTurn,
    SingleTurn,
)
from redteam_contracts.contract import ContractSpec


class BundleIncomplete(FileNotFoundError):
    pass


@dataclass(frozen=True)
class Bundle:
    """Compatibility view used by local fixtures and package-level tests."""

    document: CatalogueDocument

    @property
    def catalogue(self) -> Catalogue:
        return as_catalogue(self.document)

    @property
    def contract(self) -> ContractSpec:
        return contract_of(self.document)

    @property
    def needs_base(self) -> frozenset[str]:
        return frozenset(s.id for s in self.document.strategies if s.requires_brain)

    @property
    def delivery(self) -> dict[str, Any] | None:
        entries = {
            strategy.id: {
                "turns": "many",
                "attacker": strategy.interaction.attacker,
                "max_turns": strategy.interaction.max_turns,
            }
            for strategy in self.document.strategies
            if isinstance(strategy.interaction, AdaptiveMultiTurn)
        }
        return {"delivery": entries} if entries else None

    @property
    def entity_kinds(self) -> tuple[str, ...]:
        return tuple(sorted({s.entity_kind for s in self.document.strategies}))

    def document_for(self, catalogue: Catalogue) -> CatalogueDocument:
        """Adapt a modified local fixture catalogue back to schema v2."""
        original = {strategy.id: strategy for strategy in self.document.strategies}
        strategies = []
        for strategy in catalogue.strategies:
            previous = original.get(strategy.id)
            requires_brain = (
                previous.requires_brain
                if previous is not None
                else "{premise}" in strategy.phrasing_hint
            )
            interaction: AdaptiveMultiTurn | ScriptedMultiTurn | SingleTurn
            if previous is not None and isinstance(previous.interaction, AdaptiveMultiTurn):
                interaction = previous.interaction.model_copy(
                    update={"opening": strategy.phrasing_hint}
                )
            elif previous is not None and isinstance(previous.interaction, ScriptedMultiTurn):
                interaction = previous.interaction.model_copy(
                    update={
                        "messages": (strategy.phrasing_hint, *previous.interaction.messages[1:])
                    }
                )
            else:
                interaction = SingleTurn(mode="single_turn", prompt=strategy.phrasing_hint)
            strategies.append(
                {
                    **strategy.model_dump(mode="json", exclude={"phrasing_hint"}),
                    "requires_brain": requires_brain,
                    "interaction": interaction,
                }
            )
        return self.document.model_copy(
            update={
                "plugins": tuple(
                    CataloguePlugin.model_validate(plugin.model_dump(mode="json"))
                    for plugin in catalogue.plugins
                ),
                "strategies": tuple(
                    CatalogueStrategy.model_validate(strategy) for strategy in strategies
                ),
            }
        )


def load_bundle(path: Path) -> Bundle:
    """Read one v2 file, or convert an old directory only when a local fixture still names it."""
    source = path
    if path.is_dir() or (not path.exists() and path.with_suffix(".json").is_file()):
        adjacent = path.with_suffix(".json")
        if adjacent.is_file():
            source = adjacent
        else:
            raise BundleIncomplete(f"{path} has no adjacent schema-v2 fixture {adjacent.name}")
    if not source.is_file():
        raise BundleIncomplete(f"{source} is not a catalogue YAML or JSON file")
    loaded = yaml.safe_load(source.read_text())
    if not isinstance(loaded, dict):
        raise ValueError(f"{source} must hold a mapping")
    return Bundle(CatalogueDocument.model_validate(loaded))
