"""The test the store's design asks for by name.

All of the platform's durability rests on one property: the key of a work unit is derivable from the
plan without having executed it. If it breaks, nothing raises -- the runner just concludes nothing
was done and attacks the assistant all over again. So the property is pinned here, and pinned
**across processes**, because that is where the interesting ways to break it live: a hash seeded per
interpreter, a set iterated in memory-address order, an id built from `id()` or from the clock.
"""

from __future__ import annotations

import json
import subprocess
import sys
import textwrap

import pytest

from redteam_contracts.plan import PlannedProbe, attack_id, expand

PROBES = [
    PlannedProbe(probe_id="probe-b", plugin="invented-entity", strategy="ask-fake"),
    PlannedProbe(probe_id="probe-a", plugin="invented-entity", strategy="escalate-fake"),
    PlannedProbe(probe_id="probe-c", plugin=None, strategy="ask-scope"),
]
PARAMS = {"strategy": "mutate_to_fake", "depth": 4, "escalate": True}

_EXPAND_IN_A_FRESH_PROCESS = textwrap.dedent("""
    import json
    from redteam_contracts.plan import PlannedProbe, expand

    probes = [PlannedProbe.model_validate(p) for p in json.loads({probes!r})]
    plan = expand("run-1", probes, json.loads({params!r}), 3)
    print(json.dumps([f"{{u.attack_id}}/{{u.replica_idx}}" for u in plan.units]))
""")


def _keys_from_a_separate_process() -> list[str]:
    source = _EXPAND_IN_A_FRESH_PROCESS.format(
        probes=json.dumps([p.model_dump() for p in PROBES]),
        params=json.dumps(PARAMS),
    )
    completed = subprocess.run(
        [sys.executable, "-c", source], capture_output=True, text=True, check=True
    )
    return list(json.loads(completed.stdout))


def _keys_here() -> list[str]:
    return [f"{u.attack_id}/{u.replica_idx}" for u in expand("run-1", PROBES, PARAMS, 3).units]


def test_two_processes_expand_the_same_spec_to_the_same_keys() -> None:
    assert _keys_here() == _keys_from_a_separate_process()


def test_the_order_is_stable_regardless_of_how_the_probes_arrive() -> None:
    """A shuffled probe set must not produce a different plan: the sort is on the key."""
    forward = [u.attack_id for u in expand("run-1", PROBES, PARAMS, 2).units]
    backward = [u.attack_id for u in expand("run-1", list(reversed(PROBES)), PARAMS, 2).units]
    assert forward == backward


def test_param_ordering_does_not_change_the_identity() -> None:
    """Two planners that built the same params in a different order mean the same attack."""
    reordered = {key: PARAMS[key] for key in reversed(list(PARAMS))}
    assert attack_id("probe-a", PARAMS) == attack_id("probe-a", reordered)


def test_different_params_are_a_different_attack() -> None:
    assert attack_id("probe-a", PARAMS) != attack_id("probe-a", {**PARAMS, "depth": 5})


def test_labels_are_not_part_of_the_identity() -> None:
    """Relabelling a catalogue must not make a resumed run forget its traces."""
    labelled = expand("run-1", PROBES[:1], PARAMS, 1).units[0]
    relabelled = expand(
        "run-1", [PlannedProbe(probe_id="probe-b", plugin="other")], PARAMS, 1
    ).units[0]
    assert labelled.attack_id == relabelled.attack_id
    assert labelled == relabelled


def test_replicas_of_one_attack_share_its_identity() -> None:
    """N is a parameter of the plan, not of the attack's identity."""
    units = list(expand("run-1", PROBES[:1], PARAMS, 4).units)
    assert len({u.attack_id for u in units}) == 1
    assert sorted(u.replica_idx for u in units) == [0, 1, 2, 3]


def test_a_run_needs_at_least_one_replica() -> None:
    with pytest.raises(ValueError, match="at least one replica"):
        expand("run-1", PROBES, PARAMS, 0)


def test_attack_params_cannot_be_mutated_after_the_key_exists() -> None:
    """The sharpest way to break the layout quietly.

    `frozen=True` stops a field being reassigned; it does nothing about mutating a dict the field
    holds. Editing the params changes the `attack_id`, so keys already derived from it stop matching
    and the runner re-attacks everything -- with nothing raising along the way.
    """
    unit = expand("run-1", PROBES[:1], PARAMS, 1).units[0]
    before = unit.attack_id
    with pytest.raises(TypeError):
        unit.attack_params["depth"] = 99  # type: ignore[index]
    assert unit.attack_id == before


def test_a_unit_is_hashable_by_the_key_it_will_occupy() -> None:
    """Resumption is a set difference, so units live in sets."""
    units = expand("run-1", PROBES, PARAMS, 2).units
    assert len(set(units)) == len(units)


def test_the_plan_counts_what_it_aims_at_by_plugin_and_strategy() -> None:
    plan = expand("run-1", PROBES, PARAMS, 2)
    assert plan.planned() == 6
    assert plan.planned(plugin="invented-entity") == 4
    assert plan.planned(strategy="ask-scope") == 2
    assert plan.planned(plugin="invented-entity", strategy="ask-fake") == 2
    assert plan.plugins == frozenset({"invented-entity"})
    assert plan.strategies == frozenset({"ask-fake", "escalate-fake", "ask-scope"})
    assert [u.is_control for u in plan.units if u.strategy == "ask-scope"] == [True, True]
