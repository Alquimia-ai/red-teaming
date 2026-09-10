"""The delivery sidecar: how a strategy's probe reaches the assistant, declared beside it.

A strategy declares what premise it attacks with (`transform`) and what it says (`phrasing_hint`).
How the exchange is delivered -- one static turn, or a conversation an attacker model steers toward
the plugin's objective -- is a third axis, and gaussia's `StrategySpec` has no field for it: having
no `model_config`, it drops an unknown key silently. So the declaration is data beside the
catalogue, versioned with it, exactly as the grounding is and for the same reason. Store logic
only, so the API's entry gate can refuse a run whose catalogues name an attacker the spec does not
bind without reading the catalogue through gaussia.

**Absent means static.** Every catalogue published before this existed carries no declaration, and
every strategy it carries is delivered as one turn -- which is what it always was.

**The catalogue names an attacker by id and never a model.** Model ids stay out of published
assets: a versioned catalogue naming one freezes the choice forever, while the model has to stay
the run's decision, with its own credential and its own line in the provenance. The id is a
requirement the run satisfies in `RunSpec.attackers`, the same indirection `secret_ref` makes one
level down.

**An unknown key is refused, not ignored.** The sidecar exists because a schema that drops keys in
silence turns a declaration into nothing, and a `max_turn` with a typo that quietly delivers one
turn is the same failure one level up. It is also what keeps `"model"` out: a key this module does
not know is a key the catalogue may not carry.

The shape is `{"delivery": {strategy id: {"turns": "many", "attacker": id, "max_turns": n}}}`.
"""

from __future__ import annotations

import json
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from redteam_store import grounding, layout
from redteam_store.interface import ObjectNotFound, ObjectStore

BLOCK = "delivery"
"""The sidecar's one key, named for the axis it declares."""

FIELDS = ("turns", "attacker", "max_turns")
"""Everything a declaration may say. Anything else is refused by name."""

DEFAULT_MAX_TURNS = 6
"""Agent turns a conducted conversation may take when the sidecar does not say.

Counted on the agent's side: the opening is turn one, so a default of six is five follow-ups. Enough
for an escalation to build toward its objective and few enough that a strategy nobody bounded cannot
spend a run's budget on one conversation. A catalogue that wants more says so.
"""

MIN_MAX_TURNS = 2
"""One turn is the static delivery, and a conducted conversation of one turn is that delivery with
an attacker attached and nothing for it to do."""


class Turns(StrEnum):
    """How many exchanges one probe becomes."""

    ONE = "one"
    """The probe's query is sent, the answer is read, and that is the conversation."""

    MANY = "many"
    """The probe's query opens a conversation an attacker steers toward the plugin's objective."""


@dataclass(frozen=True)
class Delivery:
    """How one strategy's probe is delivered. The default is what every strategy did before this."""

    turns: Turns = Turns.ONE
    attacker: str | None = None
    """The id of the attacker that writes the follow-up turns. An id, never a model: the run binds
    it in `RunSpec.attackers`. Required for `many`, refused for `one`."""

    max_turns: int = DEFAULT_MAX_TURNS
    """Agent turns the conversation may take before it is closed as it stands."""

    @property
    def conducted(self) -> bool:
        return self.turns is Turns.MANY


STATIC = Delivery()
"""One turn, no attacker: the delivery of every strategy the sidecar does not mention."""


@dataclass(frozen=True)
class Objective:
    """What a plugin asks the assistant to do wrong, in the catalogue's own words.

    `PluginSpec.description` and `.principle`, read back off the published JSON. Written as
    documentation, used as instrumentation: an attacker steering a conversation is told this and
    nothing else about what it is after, so the objective is the catalogue's and never ours.
    """

    description: str
    principle: str


def normalise(raw: Mapping[str, Any]) -> dict[str, Delivery]:
    """The sidecar's `delivery` block as deliveries by strategy id, refusing what it must.

    Accepts the block or the bare mapping, the way `grounding.normalise` does.

    Raises:
        ValueError: A key this sidecar does not know; `turns` outside its two values; `many` naming
            no attacker; `one` naming an attacker or a bound nothing would use; a bound below two.
            Every one is refused by the strategy's name, so the catalogue's author knows which
            line to fix.
    """
    block: Any = raw.get(BLOCK, raw)
    if not isinstance(block, Mapping):
        raise ValueError(
            f"{BLOCK!r} must map strategy ids to declarations, not {type(block).__name__}"
        )
    deliveries: dict[str, Delivery] = {}
    for strategy, declared in block.items():
        identifier = str(strategy).strip()
        if not identifier:
            raise ValueError(f"{BLOCK!r} carries a blank strategy id")
        if not isinstance(declared, Mapping):
            raise ValueError(
                f"delivery for {identifier!r} must be a mapping, not {type(declared).__name__}"
            )
        unknown = sorted(set(map(str, declared)) - set(FIELDS))
        if unknown:
            raise ValueError(
                f"delivery for {identifier!r} carries keys this sidecar does not know: {unknown}. "
                f"A key nothing reads would declare nothing, and a model never travels in a "
                f"catalogue; the fields are {list(FIELDS)}"
            )
        deliveries[identifier] = _one(identifier, declared)
    return deliveries


def _one(identifier: str, declared: Mapping[str, Any]) -> Delivery:
    spelled = str(declared.get("turns", Turns.ONE.value))
    try:
        turns = Turns(spelled)
    except ValueError as outside:
        raise ValueError(
            f"delivery for {identifier!r} declares turns={spelled!r}; the values are "
            f"{[t.value for t in Turns]}"
        ) from outside
    attacker = declared.get("attacker")
    bound = declared.get("max_turns")
    if turns is Turns.ONE:
        if attacker is not None or bound is not None:
            raise ValueError(
                f"delivery for {identifier!r} declares one turn and names an attacker or a bound "
                f"nothing would use; drop them, or declare turns='many'"
            )
        return STATIC
    named = str(attacker).strip() if attacker is not None else ""
    if not named:
        raise ValueError(
            f"delivery for {identifier!r} declares many turns and names no attacker to write them"
        )
    max_turns = DEFAULT_MAX_TURNS if bound is None else _bound(identifier, bound)
    return Delivery(turns=Turns.MANY, attacker=named, max_turns=max_turns)


def _bound(identifier: str, raw: Any) -> int:
    if isinstance(raw, bool) or not isinstance(raw, int):
        raise ValueError(
            f"delivery for {identifier!r} declares max_turns={raw!r}, which is not a whole number"
        )
    if raw < MIN_MAX_TURNS:
        raise ValueError(
            f"delivery for {identifier!r} declares max_turns={raw}; at least {MIN_MAX_TURNS}, "
            f"because one turn is the static delivery"
        )
    return raw


def encode(deliveries: Mapping[str, Delivery]) -> bytes:
    block = {
        strategy: (
            {"turns": d.turns.value, "attacker": d.attacker, "max_turns": d.max_turns}
            if d.conducted
            else {"turns": d.turns.value}
        )
        for strategy, d in deliveries.items()
    }
    return json.dumps({BLOCK: block}, sort_keys=True, separators=(",", ":")).encode("utf-8")


def load(store: ObjectStore, name: str, version: int) -> dict[str, Delivery]:
    """What one catalogue version declares about delivery, or nothing.

    A catalogue with no sidecar declares nothing, and that is a fact rather than an error: every
    catalogue published before this existed is in that position, and every one of its strategies is
    delivered as one turn.
    """
    try:
        raw = store.get(layout.catalogue_delivery(name, version))
    except ObjectNotFound:
        return {}
    return normalise(json.loads(raw))


def merged(store: ObjectStore, versions: Mapping[str, int]) -> dict[str, Delivery]:
    """How every strategy of every catalogue a run froze is delivered, by the version it froze.

    **Every strategy, not every declaration.** Absence is a declaration too -- a catalogue with no
    sidecar delivers each of its strategies as one turn -- so a catalogue that says nothing about
    `s` and one that conducts `s` disagree, and the disagreement is refused. Read off the explicit
    entries alone, the conducted declaration silently applied to both catalogues' probes: generation
    treats each catalogue on its own and two catalogues may carry one strategy id, and the runner
    asks about an id in the context of the run's whole set of catalogues, so two answers is none.
    """
    deliveries: dict[str, Delivery] = {}
    delivered_by: dict[str, str] = {}
    for name, version in versions.items():
        declared = load(store, name, version)
        for strategy in grounding.strategies(store, name, version):
            identifier = str(strategy["id"])
            delivery = declared.get(identifier, STATIC)
            if identifier in deliveries and deliveries[identifier] != delivery:
                raise ValueError(
                    f"strategy {identifier!r} is delivered differently by two catalogues: "
                    f"{_spelled(deliveries[identifier])} by {delivered_by[identifier]!r} and "
                    f"{_spelled(delivery)} by {name!r}; a catalogue that declares nothing delivers "
                    f"one turn, and the runner cannot conduct one id two ways"
                )
            deliveries[identifier] = delivery
            delivered_by[identifier] = name
    return deliveries


def _spelled(delivery: Delivery) -> str:
    if not delivery.conducted:
        return "one turn"
    return f"{delivery.max_turns} turns through {delivery.attacker!r}"


def attackers_named(
    store: ObjectStore,
    versions: Mapping[str, int],
    *,
    grounded: bool,
    plugins: Sequence[str] = (),
    strategies: Sequence[str] = (),
) -> frozenset[str]:
    """The attacker ids the strategies this run will generate are delivered through.

    Two rules decide which strategies a run generates, and both are restated here rather than
    imported, because they live in the catalogue package and this package may not depend on
    gaussia. `generatable` keeps the half that matches the run's shape: with a base, the strategies
    that need one; without, the ones that stand alone. `narrow` keeps what the selectors name, and
    a control always. A test in the catalogue package holds the restatement against the originals,
    so the two cannot drift apart in silence.

    An attacker named by a strategy the run will not generate is not named: a grounded run over a
    catalogue whose escalation strategy carries no premise slot never conducts it, and asking that
    run to bind an attacker it will never build would be a requirement about nothing.

    Raises:
        ValueError: Two of the run's catalogues deliver one strategy id differently -- see `merged`.
            Refused here, at the gate, rather than by the runner after generation.
    """
    deliveries = merged(store, versions)
    if not any(delivery.conducted for delivery in deliveries.values()):
        return frozenset()
    wanted_plugins = frozenset(plugins)
    wanted_strategies = frozenset(strategies)
    named: set[str] = set()
    for name, version in versions.items():
        needs = grounding.needs_a_base(store, name, version)
        for strategy in grounding.strategies(store, name, version):
            identifier = str(strategy["id"])
            delivery = deliveries.get(identifier)
            if delivery is None or delivery.attacker is None:
                continue
            if (identifier in needs) is not grounded:
                continue
            plugin = strategy.get("plugin")
            selected = plugin is None or (
                (not wanted_strategies or identifier in wanted_strategies)
                and (not wanted_plugins or plugin in wanted_plugins)
            )
            if selected:
                named.add(delivery.attacker)
    return frozenset(named)


def objectives(
    store: ObjectStore, versions: Mapping[str, int], *, only: Collection[str] | None = None
) -> dict[str, Objective]:
    """The objective of each plugin in `only`, by plugin id, across the catalogues a run froze.

    Read off the published JSON rather than through gaussia's `Catalogue`, for the reason
    `grounding.strategies` gives: the coupling is two required fields of a published schema. A
    plugin id described differently by two catalogues is refused, as a pair declared twice is --
    **but only among the plugins asked for.** An objective is what an attacker is told, so only the
    plugins of conducted strategies need one, and two catalogues that describe some other plugin in
    their own words are two individually valid catalogues a static run has always been free to name
    together. `None` asks for every plugin, and is the reader's business to want.
    """
    wanted = None if only is None else frozenset(only)
    found: dict[str, Objective] = {}
    for name, version in versions.items():
        raw = json.loads(store.get(layout.catalogue(name, version)))
        for plugin in raw.get("plugins", ()):
            identifier = str(plugin["id"])
            if wanted is not None and identifier not in wanted:
                continue
            objective = Objective(
                description=str(plugin.get("description", "")),
                principle=str(plugin.get("principle", "")),
            )
            if identifier in found and found[identifier] != objective:
                raise ValueError(
                    f"plugin {identifier!r} is described differently by two catalogues"
                )
            found[identifier] = objective
    return found
