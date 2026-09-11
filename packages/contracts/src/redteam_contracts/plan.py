"""The work plan: what a run intends to do, and the keys that intent implies.

Everything durable in the platform rests on one property, and it lives here: **the key of a work
unit is derivable from the plan without having executed it.** Because it is, "the key exists" and
"the unit completed" are the same statement, and progress, resume and coverage all become the same
difference over the same keys -- with no progress table to drift out of sync.

The failure mode if that breaks is silent. Nothing raises: the runner resumes, diffs the plan
against the store, finds no key of the plan among the ones that exist, and concludes nothing was
done. It attacks the assistant all over again, doubling the cost and the load on somebody else's
infrastructure, and the final result carries duplicate traces that inflate the denominator.

So nothing that enters `attack_id` may depend on the moment of execution: no timestamp, no random
value, no process counter, no ordering the planner happened to expand in.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from types import MappingProxyType
from typing import Annotated, Any

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, PlainSerializer

_DIGEST_CHARS = 32
"""Half a sha256, hex. Long enough that a collision is not a thing that happens, short enough that a
key stays readable in a bucket listing -- and an operator reading keys is a real use."""


def _canonical(value: Any) -> str:
    """Serialise deterministically, across processes and across runs.

    `sort_keys` because a dict's insertion order is not part of its meaning, and two planners that
    built the same params in a different order must produce the same key. `separators` because
    whitespace is not meaning either.
    """
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def attack_id(probe_id: str, attack_params: Mapping[str, Any]) -> str:
    """The identity of an attack: its probe and the parameters that shape it.

    Not the replica index -- replicas of one attack share an `attack_id` and differ by their
    position under it. That is what makes N a parameter of the plan rather than of the identity.
    The labels a unit carries are not in the hash either: what a probe charges is a fact about the
    catalogue, and relabelling a catalogue must not make a resumed run forget its traces.
    """
    payload = _canonical({"probe_id": probe_id, "attack_params": dict(attack_params)})
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:_DIGEST_CHARS]


def _freeze(value: Mapping[str, Any]) -> Mapping[str, Any]:
    return MappingProxyType(dict(value))


FrozenParams = Annotated[
    Mapping[str, Any],
    AfterValidator(_freeze),
    PlainSerializer(dict, return_type=dict, when_used="always"),
]
"""Attack parameters that cannot be edited after the key was derived from them.

`frozen=True` on a pydantic model stops the *fields* being reassigned; it does nothing about
mutating a dict one of them holds. And mutating these changes the `attack_id` -- after keys were
computed from it, and with nothing raising. That is the silent duplication the whole layout is
built to avoid, so the mapping is frozen for real rather than by convention.
"""


class PlannedProbe(BaseModel):
    """What the plan needs to know about one probe: its identity, and what it charges.

    The labels come from the catalogue the probe was generated from. A control -- a strategy with
    no plugin -- charges nothing and is planned all the same: it is sent, graded and excluded from
    every rate, and its trace is evidence like any other.
    """

    model_config = ConfigDict(frozen=True)

    probe_id: str
    plugin: str | None = None
    """The risk family the probe charges. `None` for a control."""

    strategy: str | None = None
    """How the probe was built, by the strategy's id."""


class WorkUnit(BaseModel):
    """One replica of one attack: the smallest thing that produces a complete trace."""

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    probe_id: str
    attack_params: FrozenParams = Field(default_factory=dict)
    replica_idx: int = Field(ge=0)
    plugin: str | None = None
    """What this unit aims at, by risk family. Feeds the planned count per plugin, which is the
    honest denominator of everything counted afterwards. `None` for a control."""

    strategy: str | None = None

    @property
    def attack_id(self) -> str:
        return attack_id(self.probe_id, self.attack_params)

    @property
    def is_control(self) -> bool:
        return self.plugin is None

    def __hash__(self) -> int:
        """Identity is the key this unit will occupy.

        Units go into sets constantly -- resumption is a set difference -- so being hashable is
        not a convenience. Hashing on the derived key rather than on the fields also means two
        units that will collide in the store compare equal here, which is the behaviour a diff
        wants.
        """
        return hash((self.attack_id, self.replica_idx))

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, WorkUnit):
            return NotImplemented
        return (self.attack_id, self.replica_idx) == (other.attack_id, other.replica_idx)


class Plan(BaseModel):
    """The expanded plan. This is what coverage calls **planned**.

    Without it there is no denominator and no way to know whether a run finished.
    """

    model_config = ConfigDict(frozen=True)

    run_id: str
    units: tuple[WorkUnit, ...]

    @property
    def attack_ids(self) -> frozenset[str]:
        return frozenset(u.attack_id for u in self.units)

    @property
    def plugins(self) -> frozenset[str]:
        return frozenset(u.plugin for u in self.units if u.plugin is not None)

    @property
    def strategies(self) -> frozenset[str]:
        return frozenset(u.strategy for u in self.units if u.strategy is not None)

    def planned(self, *, plugin: str | None = None, strategy: str | None = None) -> int:
        """How many units the plan aims at a plugin, a strategy, or both. Everything when neither
        is named."""
        return sum(
            1
            for u in self.units
            if (plugin is None or u.plugin == plugin)
            and (strategy is None or u.strategy == strategy)
        )


def expand(
    run_id: str,
    probes: Iterable[PlannedProbe],
    attack_params: Mapping[str, Any],
    replicas: int,
) -> Plan:
    """Turn a frozen spec into the concrete list of work units. Pure, and deterministic.

    Deterministic includes the order: the units are sorted by the key they will occupy, so two
    processes expanding the same spec produce not just the same set but the same sequence.
    Sorting on the key rather than on the input order is what makes that true even if the probe set
    arrives shuffled.
    """
    if replicas < 1:
        raise ValueError(f"a run needs at least one replica per attack, got {replicas}")

    units = [
        WorkUnit(
            probe_id=probe.probe_id,
            attack_params=dict(attack_params),
            replica_idx=index,
            plugin=probe.plugin,
            strategy=probe.strategy,
        )
        for probe in probes
        for index in range(replicas)
    ]
    units.sort(key=lambda u: (u.attack_id, u.replica_idx))
    return Plan(run_id=run_id, units=tuple(units))
