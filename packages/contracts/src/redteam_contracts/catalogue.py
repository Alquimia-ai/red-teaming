"""The complete, portable catalogue document stored as one immutable object."""

from __future__ import annotations

import re
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

PREMISE_SLOT = "{premise}"
_BCP47 = re.compile(r"^[A-Za-z]{2,8}(?:-[A-Za-z0-9]{1,8})*$")

LocalizedText = str | dict[str, str]


def resolve_text(value: LocalizedText, language: str) -> str:
    """Resolve a localized field without falling back to another language."""
    if isinstance(value, str):
        return value
    try:
        return value[language]
    except KeyError as missing:
        raise ValueError(
            f"localized content has no exact {language!r} entry; available languages are "
            f"{sorted(value)}"
        ) from missing


def _validate_localized(value: LocalizedText, field: str) -> None:
    if isinstance(value, str):
        if not value.strip():
            raise ValueError(f"{field} cannot be blank")
        return
    if not value:
        raise ValueError(f"{field} must declare at least one language")
    for language, text in value.items():
        if not _BCP47.fullmatch(language):
            raise ValueError(f"{field} language {language!r} is not a BCP-47 tag")
        if not text.strip():
            raise ValueError(f"{field}[{language!r}] cannot be blank")


class SingleTurn(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    mode: Literal["single_turn"]
    prompt: LocalizedText

    @model_validator(mode="after")
    def validate_prompt(self) -> SingleTurn:
        _validate_localized(self.prompt, "interaction.prompt")
        return self


class ScriptedMultiTurn(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    mode: Literal["scripted_multi_turn"]
    messages: tuple[LocalizedText, ...] = Field(min_length=2)

    @model_validator(mode="after")
    def validate_messages(self) -> ScriptedMultiTurn:
        for index, message in enumerate(self.messages):
            _validate_localized(message, f"interaction.messages[{index}]")
        return self


class AdaptiveMultiTurn(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    mode: Literal["adaptive_multi_turn"]
    opening: LocalizedText
    attacker: str = Field(min_length=1)
    max_turns: int = Field(ge=2)

    @model_validator(mode="after")
    def validate_opening(self) -> AdaptiveMultiTurn:
        _validate_localized(self.opening, "interaction.opening")
        return self


Interaction = Annotated[
    SingleTurn | ScriptedMultiTurn | AdaptiveMultiTurn,
    Field(discriminator="mode"),
]


class CataloguePlugin(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    description: str = Field(min_length=1)
    principle: str = Field(min_length=1)


class CatalogueStrategy(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    description: str = Field(min_length=1)
    plugin: str | None = None
    entity_kind: str = Field(min_length=1)
    transform: str = Field(min_length=1)
    doc: Literal[0, 1]
    requires_brain: bool
    interaction: Interaction

    @model_validator(mode="after")
    def validate_brain_contract(self) -> CatalogueStrategy:
        values: tuple[LocalizedText, ...]
        if isinstance(self.interaction, SingleTurn):
            values = (self.interaction.prompt,)
        elif isinstance(self.interaction, ScriptedMultiTurn):
            values = self.interaction.messages
        else:
            values = (self.interaction.opening,)
            if self.plugin is None:
                raise ValueError("an adaptive_multi_turn strategy must name a plugin")

        texts: list[str] = []
        for localized in values:
            texts.extend([localized] if isinstance(localized, str) else localized.values())
        carries_premise = any(PREMISE_SLOT in text for text in texts)
        if self.requires_brain and not carries_premise:
            raise ValueError(
                f"strategy {self.id!r} requires a brain but its interaction has no {PREMISE_SLOT}"
            )
        if not self.requires_brain and carries_premise:
            raise ValueError(
                f"strategy {self.id!r} does not require a brain but uses {PREMISE_SLOT}"
            )
        return self

    def messages(self, language: str) -> tuple[str, ...]:
        if isinstance(self.interaction, SingleTurn):
            return (resolve_text(self.interaction.prompt, language),)
        if isinstance(self.interaction, ScriptedMultiTurn):
            return tuple(resolve_text(message, language) for message in self.interaction.messages)
        return (resolve_text(self.interaction.opening, language),)


class CatalogueDocument(BaseModel):
    """Schema v2: one digest covers behavior, strategies, and delivery."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[2]
    name: str = Field(min_length=1)
    contract: dict[str, Any]
    plugins: tuple[CataloguePlugin, ...]
    strategies: tuple[CatalogueStrategy, ...]

    @model_validator(mode="after")
    def validate_references(self) -> CatalogueDocument:
        plugin_ids = [plugin.id for plugin in self.plugins]
        strategy_ids = [strategy.id for strategy in self.strategies]
        if len(plugin_ids) != len(set(plugin_ids)):
            raise ValueError("plugin ids must be unique")
        if len(strategy_ids) != len(set(strategy_ids)):
            raise ValueError("strategy ids must be unique")
        unknown = sorted(
            {strategy.plugin for strategy in self.strategies if strategy.plugin} - set(plugin_ids)
        )
        if unknown:
            raise ValueError(f"strategies name unknown plugins: {unknown}")
        return self

    def strategy(self, identifier: str) -> CatalogueStrategy:
        try:
            return next(strategy for strategy in self.strategies if strategy.id == identifier)
        except StopIteration as missing:
            raise KeyError(identifier) from missing
