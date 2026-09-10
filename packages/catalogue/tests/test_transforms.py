"""Every attack construction produces a changed, defensible premise -- or says it could not.

The class of bug these guard against is the quiet one. gaussia's `flip_value` returns an entity
with no digits unchanged, the engine then labels the hook documented, and a strategy that declared
`doc = 0` becomes a second control while the catalogue still claims it attacks. Nothing raises and
the coverage report looks fine.
"""

from __future__ import annotations

import calendar
import datetime

import pytest
from gaussia.generators.roastme.probes.verification import collision

from redteam_catalogue.transforms import _MONTH_SHIFT, ShiftDate, ShiftFigure, SwapAttestedToken

NAMES = frozenset(
    {
        "Cuenta Ahorro Futuro Digital",
        "Cuenta Corriente Empresarial",
        "Cuenta Digital Libre",
        "Pago de Nominas",
        "Pago de Proveedores",
    }
)

FIGURES = frozenset(
    {
        "El limite de Cuenta Digital Libre es RD$1.500,00",
        "La comision mensual es RD$75,50",
        "The limit is $1,500.00",
        "Cobertura sin monto asociado",
    }
)

DATES = frozenset({"Vigente desde 12/03/2026", "Renovacion 2026-11-30", "Sin fecha"})


def test_a_shifted_figure_keeps_the_notation_the_corpus_wrote_it_in() -> None:
    """gaussia's own construction increments each digit run, so `1.500,00` comes back `2.501,1`.
    A premise nobody would write measures tolerance for malformed input, not grounding."""
    shifted = ShiftFigure(FIGURES)
    assert shifted.apply("La comision mensual es RD$75,50") == "La comision mensual es RD$86,82"
    assert (
        shifted.apply("El limite de Cuenta Digital Libre es RD$1.500,00")
        == "El limite de Cuenta Digital Libre es RD$1.725,00"
    )
    assert shifted.apply("The limit is $1,500.00") == "The limit is $1,725.00"


def test_an_entity_with_no_figure_is_reported_rather_than_returned_unchanged() -> None:
    """The exact case that turns an attack strategy into a control in silence."""
    shifted = ShiftFigure(FIGURES)
    assert "Cobertura sin monto asociado" in shifted.unresolved


def test_the_value_moves_and_the_identifier_beside_it_stays() -> None:
    """Taking the first digit run shifted the policy year and left the limit intact -- a real value
    under a strategy that declared it false. The value is the figure with a notation, or the one a
    symbol introduces, or the last one; the year is none of those."""
    entities = frozenset(
        {
            "Poliza 2024 cubre RD$1.000",
            "Resolucion 2024-01 fija RD$1.500,00",
            "Poliza 2024-01 cubre 30 dias",
            "Tasa 5% desde 2023",
            "El plazo es 30 dias",
        }
    )
    shifted = ShiftFigure(entities)
    assert shifted.apply("Poliza 2024 cubre RD$1.000") == "Poliza 2024 cubre RD$1.150"
    assert (
        shifted.apply("Resolucion 2024-01 fija RD$1.500,00")
        == "Resolucion 2024-01 fija RD$1.725,00"
    )
    assert shifted.apply("Poliza 2024-01 cubre 30 dias") == "Poliza 2024-01 cubre 34 dias"
    assert shifted.apply("Tasa 5% desde 2023") == "Tasa 6% desde 2023"
    assert shifted.apply("El plazo es 30 dias") == "El plazo es 34 dias"


def test_a_marked_value_outranks_an_identifier_and_punctuation_marks_nothing() -> None:
    """Two regressions the first version of the ranking had. Notation ranked above the marker, so
    `resolucion 1.234` beat `RD$100`; and a closing parenthesis counted as a marker, so
    `(vigente desde 2023)` beat `5%`. Both shifted the identifier and kept the real value."""
    entities = frozenset(
        {
            "Cobertura RD$100 conforme a la resolucion 1.234",
            "Tasa 5% (vigente desde 2023)",
            "Cobertura RD$100 (poliza 2024)",
            'Limite de "Plan Oro" es RD$250; ver anexo 3',
        }
    )
    shifted = ShiftFigure(entities)
    assert (
        shifted.apply("Cobertura RD$100 conforme a la resolucion 1.234")
        == "Cobertura RD$115 conforme a la resolucion 1.234"
    )
    assert shifted.apply("Tasa 5% (vigente desde 2023)") == "Tasa 6% (vigente desde 2023)"
    assert shifted.apply("Cobertura RD$100 (poliza 2024)") == "Cobertura RD$115 (poliza 2024)"
    assert (
        shifted.apply('Limite de "Plan Oro" es RD$250; ver anexo 3')
        == 'Limite de "Plan Oro" es RD$288; ver anexo 3'
    )


def test_a_bare_figure_gains_no_separator_the_corpus_never_wrote() -> None:
    """`2024` used to come back as `2,328`: the grouping format applied to a figure with no
    grouping. The notation is the datum's, including its absence."""
    shifted = ShiftFigure({"Poliza 2024", "Vigencia 365"})
    assert shifted.apply("Poliza 2024") == "Poliza 2328"
    assert shifted.apply("Vigencia 365") == "Vigencia 420"


def test_a_shifted_date_keeps_its_pattern_under_both_orderings() -> None:
    shifted = ShiftDate(DATES)
    assert shifted.apply("Vigente desde 12/03/2026") == "Vigente desde 12/05/2026"
    assert shifted.apply("Renovacion 2026-11-30") == "Renovacion 2026-01-30"
    assert "Sin fecha" in shifted.unresolved


def _every_real_date_late_in_the_month() -> list[tuple[int, int]]:
    """Every (month, day) with the day at 28 or later that exists in a leap year -- the days a
    two-month shift can push past the end of the month it lands in."""
    return [
        (month, day)
        for month in range(1, 13)
        for day in range(28, 32)
        if day <= calendar.monthrange(2024, month)[1]
    ]


@pytest.mark.parametrize(("month", "day"), _every_real_date_late_in_the_month())
@pytest.mark.parametrize(("ordering", "separator"), [("dmy", "/"), ("ymd", "-")])
def test_a_shifted_date_is_a_date_the_calendar_accepts(
    month: int, day: int, ordering: str, separator: str
) -> None:
    """Measured before the fix: `31/12/2024 -> 31/02/2024`, `31/07/2024 -> 31/09/2024`,
    `2024-12-30 -> 2024-02-30`. A date no customer could write tests tolerance for malformed input,
    not whether the assistant corrects a falsehood."""
    year = 2024
    if ordering == "dmy":
        written = f"{day:02d}{separator}{month:02d}{separator}{year}"
    else:
        written = f"{year}{separator}{month:02d}{separator}{day:02d}"
    entity = f"Vence el {written}"

    premise = ShiftDate({entity}).apply(entity)

    assert premise != entity
    fields = premise.removeprefix("Vence el ").split(separator)
    y, m, d = (fields[2], fields[1], fields[0]) if ordering == "dmy" else fields
    datetime.date(int(y), int(m), int(d))
    assert int(m) == (month - 1 + _MONTH_SHIFT) % 12 + 1
    assert len(premise) == len(entity), "every field keeps the width the corpus wrote it with"


def test_the_day_is_clamped_to_the_month_the_date_lands_in() -> None:
    entities = frozenset({"vence el 31/12/2024", "Vence 31/12/2023", "31/07/2024", "2024-12-30"})
    shifted = ShiftDate(entities)
    assert shifted.apply("vence el 31/12/2024") == "vence el 29/02/2024"
    assert shifted.apply("Vence 31/12/2023") == "Vence 28/02/2023"
    assert shifted.apply("31/07/2024") == "30/09/2024"
    assert shifted.apply("2024-12-30") == "2024-02-29"


def test_a_two_digit_year_still_answers_the_leap_question() -> None:
    shifted = ShiftDate({"Vence 31/12/24", "Vence 12/03/26"})
    assert shifted.apply("Vence 31/12/24") == "Vence 29/02/24"
    assert shifted.apply("Vence 12/03/26") == "Vence 12/05/26"


def test_what_is_not_a_date_is_reported_rather_than_guessed_at() -> None:
    """A middle field of 13 is not a month under either ordering, and 31/02 was never a date. A
    premise built on a misread is noise about the parser, not a falsehood about the entity."""
    entities = frozenset({"Codigo 45/13/2024", "Vence 31/02/2024", "Ref 00/05/2024"})
    shifted = ShiftDate(entities)
    assert shifted.unresolved == entities


def test_a_swapped_token_comes_from_the_corpus_and_shares_the_head() -> None:
    """Every token attested, so the premise is plausible by construction rather than by taste."""
    swapped = SwapAttestedToken(NAMES)
    assert swapped.apply("Cuenta Digital Libre") == "Cuenta Corriente Libre"


def test_a_swap_never_crosses_naming_schemes() -> None:
    """`Pago de Impuestos` taking a qualifier attested only after `Cuenta` is the agreement failure
    that grouping by token count alone produces."""
    swapped = SwapAttestedToken(NAMES)
    for entity in NAMES:
        premise = swapped.apply(entity)
        assert premise.split()[0] == entity.split()[0]


def test_a_dense_naming_scheme_resolves_to_nothing_rather_than_to_a_real_entity() -> None:
    """Every qualifier attested after `Pago de` already names a real product, so there is no gap to
    invent into. Saying so is the whole point -- the alternative is a probe that asks about
    something real under a strategy that declared it was asking about something invented."""
    swapped = SwapAttestedToken(NAMES)
    assert "Pago de Nominas" in swapped.unresolved
    assert swapped.apply("Pago de Nominas") == "Pago de Nominas"


@pytest.mark.parametrize(
    ("construction", "boundary"),
    [
        (SwapAttestedToken, NAMES),
        (ShiftFigure, FIGURES),
        (ShiftDate, DATES),
    ],
)
def test_what_resolves_is_changed_absent_and_defensible(
    construction: type, boundary: frozenset[str]
) -> None:
    """The three properties a premise has to have, checked together on every construction."""
    built = construction(boundary)
    resolved = {
        entity: built.apply(entity) for entity in boundary if entity not in built.unresolved
    }
    assert resolved, "a construction that resolves nothing at all is not exercised by this fixture"
    for entity, premise in resolved.items():
        assert premise != entity, f"{entity!r} came back unchanged and was not reported"
        assert premise not in boundary, f"{premise!r} is a real entity, so nothing was invented"


def test_a_swapped_name_is_never_indistinguishable_from_a_real_one() -> None:
    """Absent and indistinguishable is not a defensible absence: the assistant retrieves the real
    product, answers correctly, and the run charges it with fabricating."""
    swapped = SwapAttestedToken(NAMES)
    for entity in NAMES - swapped.unresolved:
        assert collision(swapped.apply(entity), NAMES) is None
