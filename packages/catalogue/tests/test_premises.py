"""A catalogue key resolves to configured code, and refuses when the run declared too little."""

from __future__ import annotations

import pytest
from gaussia.core.transform import Transform
from gaussia.generators.roastme.probes.transforms import TRANSFORMS

from redteam_catalogue import premises
from redteam_catalogue.contextual import CONTEXTUAL_SIBLING
from redteam_catalogue.transforms import SHIFT_FIGURE, SWAP_TOKEN, SwapAttestedToken
from redteam_contracts.run_spec import ProbeContext

BOUNDARY = frozenset({"Cuenta Digital Libre", "Cuenta Corriente Empresarial", "Pago de Nominas"})


def _another_builder(ingredients: premises.Ingredients) -> Transform:
    return SwapAttestedToken(ingredients.boundary)


CONTEXT = ProbeContext(language="es-419", domain="banca minorista")


def test_a_declared_key_resolves_to_a_construction_closed_over_the_corpus() -> None:
    [built] = premises.build_transforms([SWAP_TOKEN], premises.Ingredients(boundary=BOUNDARY))
    assert built.key == SWAP_TOKEN
    assert built.apply("Cuenta Digital Libre") == "Cuenta Corriente Libre"


def test_gaussia_s_own_keys_are_left_to_gaussia() -> None:
    """They need no configuration, and resolving them here would be a second registry that can
    disagree with the one catalogue validation checks against."""
    assert premises.build_transforms(tuple(TRANSFORMS), premises.Ingredients(BOUNDARY)) == ()


def test_the_sequence_is_ordered_so_a_run_is_reproducible() -> None:
    built = premises.build_transforms(
        [SHIFT_FIGURE, SWAP_TOKEN, SHIFT_FIGURE], premises.Ingredients(BOUNDARY)
    )
    assert [transform.key for transform in built] == [SHIFT_FIGURE, SWAP_TOKEN]


def test_a_model_driven_key_without_a_context_is_refused_before_a_probe_exists() -> None:
    """A model asked for Spanish premises with no language in front of it answers in the language
    of the prompt, and the run then measures English questions about Spanish products."""
    with pytest.raises(premises.ContextRequired, match="context"):
        premises.build_transforms([CONTEXTUAL_SIBLING], premises.Ingredients(BOUNDARY))


def test_a_model_driven_key_without_a_generator_is_refused() -> None:
    with pytest.raises(premises.ContextRequired, match="generator"):
        premises.build_transforms(
            [CONTEXTUAL_SIBLING], premises.Ingredients(BOUNDARY, context=CONTEXT)
        )


def test_what_no_construction_could_build_is_reported_per_key() -> None:
    """The number worth reading before a run is trusted."""
    built = premises.build_transforms([SWAP_TOKEN], premises.Ingredients(BOUNDARY))
    assert "Pago de Nominas" in premises.unresolved(built)[SWAP_TOKEN]


def test_registering_a_different_builder_under_one_key_is_refused() -> None:
    with pytest.raises(ValueError, match="already has a builder"):
        premises.register(SWAP_TOKEN, _another_builder)
