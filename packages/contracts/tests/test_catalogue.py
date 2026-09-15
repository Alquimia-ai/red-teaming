from __future__ import annotations

import pytest
from pydantic import ValidationError

from redteam_contracts.catalogue import CatalogueDocument


def _document(**strategy: object) -> dict[str, object]:
    declared: dict[str, object] = {
        "id": "invented",
        "name": "Invented entity",
        "description": "Ask about an invented entity",
        "plugin": "grounding",
        "entity_kind": "product",
        "transform": "swap_token",
        "doc": 0,
        "requires_brain": True,
        "interaction": {
            "mode": "single_turn",
            "prompt": {"es-419": "¿Qué incluye {premise}?"},
        },
    }
    declared.update(strategy)
    return {
        "schema_version": 2,
        "name": "security",
        "contract": {"version": "v1", "verdict": {}, "principles": []},
        "plugins": [
            {
                "id": "grounding",
                "name": "Grounding",
                "description": "Grounding failures",
                "principle": "no_invention",
            }
        ],
        "strategies": [declared],
    }


def test_resolves_only_the_exact_declared_language() -> None:
    strategy = CatalogueDocument.model_validate(_document()).strategies[0]
    assert strategy.messages("es-419") == ("¿Qué incluye {premise}?",)
    with pytest.raises(ValueError, match="no exact 'es' entry"):
        strategy.messages("es")


def test_requires_brain_and_premise_slot_agree() -> None:
    with pytest.raises(ValidationError, match="requires a brain"):
        CatalogueDocument.model_validate(
            _document(interaction={"mode": "single_turn", "prompt": "Hello"})
        )
    with pytest.raises(ValidationError, match="does not require a brain"):
        CatalogueDocument.model_validate(_document(requires_brain=False))


def test_scripted_and_adaptive_modes_are_shape_checked() -> None:
    scripted = _document(
        interaction={
            "mode": "scripted_multi_turn",
            "messages": ["First {premise}", "Second"],
        }
    )
    assert len(CatalogueDocument.model_validate(scripted).strategies[0].messages("en")) == 2

    with pytest.raises(ValidationError, match="at least 2"):
        CatalogueDocument.model_validate(
            _document(interaction={"mode": "scripted_multi_turn", "messages": ["{premise}"]})
        )
    with pytest.raises(ValidationError, match="must name a plugin"):
        CatalogueDocument.model_validate(
            _document(
                plugin=None,
                interaction={
                    "mode": "adaptive_multi_turn",
                    "opening": "Open with {premise}",
                    "attacker": "crescendo",
                    "max_turns": 3,
                },
            )
        )
