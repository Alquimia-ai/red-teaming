"""Premise constructions that need no model, derived from the datum's own shape.

A transform fabricates the premise: it takes a real entity out of the knowledge base and deforms it
into the thing the probe leans on. It decides the *text* and never the label -- whether the result
is documented is the engine's call, read from its own view of the boundary.

**Why these exist at all.** gaussia ships four and says in its own docstring that three of them are
wrong outside the corpus they were written for: `mutate_to_fake` suffixes `-2`, which reads as a
typo rather than as a sibling product; `flip_value` increments every digit run, so a figure written
with thousands separators comes back mangled and an entity with no digits comes back **unchanged**
-- which the engine then labels documented, quietly turning an attack strategy into a second
control; and `flip_fact` prepends an English `not`. Measured on this repo's own fixture before any
of this was written: six of eight generated probes ended up asking about real entities.

**No word lists.** Everything here reads its rule off the entity it was handed -- the separators the
figure itself uses, the pattern the date itself follows, the tokens the corpus itself attests. A
table of Spanish qualifiers would be our vocabulary standing in for the client's, which is the same
mistake as an invented realism pool.

**The mapping is computed before the first probe, not per call.** Two things follow, and the second
is the one that matters: `apply` becomes a pure lookup, and what a construction *could not* build
is known before the run spends anything. A transform that quietly returns the entity unchanged is
exactly how a `doc = 0` strategy becomes a control, so not-built is recorded rather than
substituted.
"""

from __future__ import annotations

import calendar
import datetime
import re
import unicodedata
from abc import ABC, abstractmethod
from collections import defaultdict
from collections.abc import Iterable

from gaussia.core.transform import Transform
from gaussia.generators.roastme.probes.verification import collision

SWAP_TOKEN = "swap_token"
SHIFT_FIGURE = "shift_figure"
SHIFT_DATE = "shift_date"

_FIGURE = re.compile(r"\d[\d.,]*\d|\d")
_DATE = re.compile(r"\b(\d{1,4})([/-])(\d{1,2})\2(\d{1,4})\b")

_RELATIVE_SHIFT = 1.15
"""How far a figure moves.

Relative rather than absolute so it works at any scale, and large enough that an assistant agreeing
with it is agreeing with something plainly different -- the point is a premise a careful assistant
must correct, not one it could round to.
"""

_MONTH_SHIFT = 2
"""How far a date moves.

Two months, with the day clamped to the length of the month it lands in. The shift alone does not
keep a date valid -- measured before this was written, `31/12/2024` came back as `31/02/2024` and
`2024-12-30` as `2024-02-30`, dates no customer could write -- and a premise the calendar refuses
tests whether the assistant tolerates malformed input rather than whether it corrects a falsehood.
The year is left alone even when the month wraps, so the falsehood is the part under test rather
than the arithmetic.
"""

_YEAR_DIGITS = 4
_SHORT_YEAR_BASE = 2000
"""A two-digit year is read as this century for the one question the calendar asks of it, whether
February has 29 days. The rendered year keeps however many digits the corpus wrote."""


class MappedTransform(Transform, ABC):  # type: ignore[misc]  # gaussia ships no stubs
    """A construction that resolves its whole mapping against the boundary up front.

    Args:
        boundary: Every entity of the kind this transform will be asked about. It is the corpus'
            own vocabulary, and for `swap_token` it is the only vocabulary used.
        checks_collision: Whether a premise indistinguishable from a real entity counts as a
            failure to construct. True for name-shaped kinds, where a premise one preposition away
            from a real product makes the assistant retrieve the real one and answer correctly --
            and the run charges it with inventing. **False for sentence-shaped kinds**, because the
            near-miss thresholds are calibrated on short names: a whole statement scores above the
            ratio against its own one-digit flip, so the check would reject every legitimate
            falsification.
    """

    def __init__(self, boundary: Iterable[str], *, checks_collision: bool) -> None:
        entities = frozenset(boundary)
        self._mapping: dict[str, str] = {}
        unresolved: set[str] = set()

        for entity in sorted(entities):
            premise = self._derive(entity, entities)
            if premise is None or premise == entity or premise in entities:
                unresolved.add(entity)
                continue
            if checks_collision and collision(premise, entities - {premise}) is not None:
                unresolved.add(entity)
                continue
            self._mapping[entity] = premise

        self._unresolved = frozenset(unresolved)

    @property
    def unresolved(self) -> frozenset[str]:
        """Entities this construction could not deform into a defensible premise.

        Read by the caller and reported, never swallowed. Each one would otherwise become a probe
        asking about something real under a strategy that declared it was asking about something
        invented.
        """
        return self._unresolved

    def apply(self, entity: str) -> str:
        """The premise, or the entity itself when nothing could be built from it.

        Unchanged is the honest answer here rather than an invented one -- the engine then labels
        the hook documented, which is true. What must not happen is that being invisible, and
        `unresolved` is what makes it visible.
        """
        return self._mapping.get(entity, entity)

    @abstractmethod
    def _derive(self, entity: str, boundary: frozenset[str]) -> str | None:
        """The premise for one entity, or None when this construction has nothing to work on."""


class SwapAttestedToken(MappedTransform):
    """A sibling built only from tokens the corpus already attests.

    Every token in the result appears in a real entity of the same shape, at the same position, so
    the premise is plausible by construction rather than by our judgement of what sounds plausible.
    The combination is one the base does not carry, which is what makes it a premise rather than a
    control.

    **A candidate has to share the head of the name, and that is the whole of the grammar.**
    Measured while writing this: grouping by token count alone lets `Pago de Nóminas` take a
    qualifier attested in `Cuenta Corriente Empresarial`, and out comes `Pago de Empresarial` --
    same length, no agreement, nothing a customer would type. Restricting each position to the
    tokens attested *after the same prefix* fixes it without anybody encoding a rule about Spanish:
    `Pago de ___` may only be completed by what the corpus already writes after `Pago de`.

    **What it cannot do, stated rather than discovered.** This construction can only invent where
    the corpus has a gap. `Cuenta Digital Libre` becomes `Cuenta Corriente Libre` because the base
    happens not to carry that combination; `Pago de Nóminas` yields nothing, because every
    qualifier attested after `Pago de` already names a real product. A densely populated naming
    scheme therefore resolves to almost nothing here, and that is correct rather than a
    shortcoming -- every premise it does produce is built from attested tokens, absent from the
    base, and clear of the near-miss check.

    So this is the cheap construction, not the general one: it costs no model call and it reports,
    in `unresolved`, exactly which entities need the one that does.
    """

    @property
    def key(self) -> str:
        return SWAP_TOKEN

    def __init__(self, boundary: Iterable[str]) -> None:
        entities = frozenset(boundary)
        # (head, length) -> what the corpus writes next. The length is in the key because
        # `Pago de X` and `Pago de X Y` are different naming schemes that happen to share a head.
        self._attested: dict[tuple[tuple[str, ...], int], set[str]] = defaultdict(set)
        for entity in entities:
            tokens = entity.split()
            for position, token in enumerate(tokens):
                self._attested[(tuple(tokens[:position]), len(tokens))].add(token)
        super().__init__(entities, checks_collision=True)

    def _derive(self, entity: str, boundary: frozenset[str]) -> str | None:
        tokens = entity.split()
        # Right to left, because the trailing token is the qualifier in most naming schemes:
        # swapping it keeps the longest head and yields the closest sibling. Walking left is the
        # fallback for a name whose qualifier the corpus attests only once.
        #
        # Never position zero. The head names the scheme rather than qualifying it, so swapping it
        # crosses schemes -- measured while writing this, `Pago de Impuestos` came back as
        # `Cuenta de Impuestos`. A one-token entity therefore has no sibling this construction can
        # build, and says so through `unresolved` instead of coming back unchanged.
        for position in range(len(tokens) - 1, 0, -1):
            head = (tuple(tokens[:position]), len(tokens))
            for candidate in sorted(self._attested.get(head, set()) - {tokens[position]}):
                premise = " ".join([*tokens[:position], candidate, *tokens[position + 1 :]])
                if premise not in boundary and collision(premise, boundary) is None:
                    return premise
        return None


class ShiftFigure(MappedTransform):
    """A figure the base does not carry, written the way the base writes figures.

    The separators are read off the entity itself, so `RD$1.500,00` comes back as a well-formed
    `RD$1.725,00` rather than as the `RD$2.501,1` that incrementing each digit run produces. A
    premise nobody would write is not a premise -- it tests whether the assistant tolerates
    malformed input.

    **Which figure moves is read off the sentence's shape, not its position.** A `limit` entity is
    sentence-shaped and the value it states tends to sit at the end, after whatever identifier,
    year or resolution number introduces it. Taking the first digit run shifted the identifier and
    left the value intact: `Poliza 2024 cubre RD$1.000` came back as `Poliza 2,328 cubre RD$1.000`,
    a real limit under a strategy that declared it false, with a separator the corpus never wrote.
    So the figure a symbol marks wins, then the one written with a notation, then the last. Nothing
    here knows what a year or a currency is; it knows what the figure looks like.
    """

    @property
    def key(self) -> str:
        return SHIFT_FIGURE

    def __init__(self, boundary: Iterable[str]) -> None:
        # Sentence-shaped entities: the near-miss thresholds are calibrated on short names and
        # would reject every legitimate falsification here.
        super().__init__(boundary, checks_collision=False)

    def _derive(self, entity: str, boundary: frozenset[str]) -> str | None:
        match = _value_of(entity)
        if match is None:
            return None
        shifted = _shift(match.group())
        if shifted is None:
            return None
        return entity[: match.start()] + shifted + entity[match.end() :]


class ShiftDate(MappedTransform):
    """A date the base does not carry, in the pattern the base wrote it in.

    The month moves and the day is clamped to the month it lands in, so the premise is a date that
    exists. A datum this construction cannot read as a date -- a middle field that is not a month,
    a day the calendar refuses -- is reported through `unresolved` rather than guessed at: a
    premise built on a misread is not a falsehood about the entity, it is noise about our parser.
    """

    @property
    def key(self) -> str:
        return SHIFT_DATE

    def __init__(self, boundary: Iterable[str]) -> None:
        super().__init__(boundary, checks_collision=False)

    def _derive(self, entity: str, boundary: frozenset[str]) -> str | None:
        match = _DATE.search(entity)
        if match is None:
            return None
        first, separator, middle, last = match.groups()
        moved = _shift_date(first, middle, last)
        if moved is None:
            return None
        shifted = separator.join(moved)
        return entity[: match.start()] + shifted + entity[match.end() :]


def _value_of(entity: str) -> re.Match[str] | None:
    """The figure that states the value, among every figure the sentence carries.

    Ranked by shape, read off the datum. First a figure a symbol marks -- a currency sign before
    it, a unit sign after it -- because that is the corpus itself saying "this is the amount"; then
    a figure written with a grouping or decimal separator over a bare one; then the last figure over
    an earlier one, because a statement puts its value after its subject. The marker outranks the
    notation because a dotted identifier is common -- `resolucion 1.234` -- and a currency figure
    written bare is too -- `RD$100` -- and the identifier must not win that pair. None of this is a
    vocabulary: a marker is recognised by its Unicode class, never by name.
    """
    matches = list(_FIGURE.finditer(entity))
    if not matches:
        return None

    def shape(match: re.Match[str]) -> tuple[bool, bool, int]:
        notation = any(character in ".," for character in match.group())
        before = entity[match.start() - 1] if match.start() else ""
        after = entity[match.end()] if match.end() < len(entity) else ""
        marked = _is_marker(before) or _is_marker(after)
        return marked, notation, match.start()

    return max(matches, key=shape)


_SYMBOL_CLASSES = "S"
"""Unicode's symbol categories -- currency (`Sc`), maths (`Sm`), other (`So`), modifier (`Sk`). What
a corpus puts beside an amount to say what kind of amount it is: `$`, `€`, `£`, `°`, `+`."""

_RATE_SIGNS = "%‰"
"""Unicode files the per-cent and per-mille signs under punctuation rather than symbols. They mark
a value as surely as a currency sign does, so they are named -- the one exception to the class
rule, and a fact about Unicode rather than about any corpus."""


def _is_marker(character: str) -> bool:
    """Whether a character beside a figure marks it as a value.

    A symbol by Unicode class, or a rate sign. Sentence punctuation is not a marker: a closing
    parenthesis, a quote or a semicolon sits beside whatever the sentence put last, and it used to
    make a parenthesised year outrank the rate the sentence was about -- `Tasa 5% (vigente desde
    2023)` moved the year and kept the rate.
    """
    if not character:
        return False
    return unicodedata.category(character).startswith(_SYMBOL_CLASSES) or character in _RATE_SIGNS


def _shift_date(first: str, middle: str, last: str) -> tuple[str, str, str] | None:
    """The three fields with the month moved and the day clamped, each keeping its width.

    The ordering is read off the match: a four-digit first field is `yyyy-mm-dd`, anything else is
    `dd/mm/yyyy` -- the two orderings a corpus uses, and the middle field is the month under both.
    `None` when the fields do not make a date, which is what `unresolved` is for.
    """
    year_first = len(first) == _YEAR_DIGITS
    year_text, day_text = (first, last) if year_first else (last, first)
    month, day = int(middle), int(day_text)
    year = int(year_text) + (_SHORT_YEAR_BASE if len(year_text) <= 2 else 0)
    if not (1 <= month <= 12 and datetime.MINYEAR <= year <= datetime.MAXYEAR):
        return None
    if not 1 <= day <= calendar.monthrange(year, month)[1]:
        return None

    moved = (month - 1 + _MONTH_SHIFT) % 12 + 1
    clamped = min(day, calendar.monthrange(year, moved)[1])
    month_text = f"{moved:0{len(middle)}d}"
    day_moved = f"{clamped:0{len(day_text)}d}"
    if year_first:
        return year_text, month_text, day_moved
    return day_moved, month_text, year_text


def _shift(figure: str) -> str | None:
    """A different figure, in the same notation.

    The decimal separator is whichever of `.` or `,` comes last and is not grouping three digits.
    Everything before it is grouped with the other one. Read off the figure rather than configured,
    because a corpus writes figures one way and that way is a fact about the corpus.
    """
    decimal_separator, grouping = _notation(figure)
    plain = figure
    if grouping:
        plain = plain.replace(grouping, "")
    if decimal_separator:
        plain = plain.replace(decimal_separator, ".")
    try:
        value = float(plain)
    except ValueError:
        return None

    places = len(plain.split(".")[1]) if "." in plain else 0
    moved = round(value * _RELATIVE_SHIFT, places)
    if moved == value:
        # Too small for a relative shift to move it at this precision. One unit of the last place
        # keeps the notation and is still a figure the base does not carry.
        moved = round(value + 10**-places, places) if places else value + 1

    # Grouped only when the figure itself was: a bare `2024` rendered through the grouping format
    # came back as `2,328`, a separator the corpus never wrote.
    rendered = f"{moved:,.{places}f}" if grouping else f"{moved:.{places}f}"
    if grouping or decimal_separator:
        rendered = rendered.replace(",", "\x00").replace(".", decimal_separator or ".")
        rendered = rendered.replace("\x00", grouping)
    if _notation(rendered) != (decimal_separator, grouping):
        # The shifted figure no longer reads the way the original did, so it is not "the same
        # figure, moved" -- it is a different notation, and that is not a premise.
        return None
    return rendered


def _notation(figure: str) -> tuple[str, str]:
    """`(decimal separator, grouping separator)`, either possibly empty."""
    separators = [character for character in figure if character in ".,"]
    if not separators:
        return "", ""
    last = separators[-1]
    tail = figure.rsplit(last, 1)[1]
    if len(tail) == 3 and len(separators) == 1 and len(figure.split(last)[0]) <= 3:
        # Ambiguous on its own -- `1.500` is either a thousand and a half or one and a half. The
        # corpus convention decides, and grouping is the reading that a currency figure almost
        # always means.
        return "", last
    if len(tail) == 3 and separators.count(last) > 1:
        return "", last
    other = next((character for character in separators if character != last), "")
    return last, other
