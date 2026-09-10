"""There is one door to the target, and the engine knows no other.

The governance -- budget, pacing, the safe-mode gate -- lives in `GovernedTarget`, and gaussia does
not know it exists. That is what makes it impossible to bypass from inside the search. It is only
impossible to bypass from inside *our* code if our code has no other way to build a target, and this
is the test that says so.
"""

from __future__ import annotations

import inspect
from typing import Any

import pytest

from redteam_contracts.run_spec import ConnectorSpec
from redteam_engine import attack, governed
from redteam_engine.governed import Budget, GovernedTarget, attackable
from redteam_target import KINDS
from redteam_target.alquimia import ALQUIMIA
from redteam_target.replay import REPLAY


class _Resolver:
    def resolve(self, ref: str) -> str:
        return f"resolved-{ref}"


def _connector(kind: str, **options: Any) -> ConnectorSpec:
    return ConnectorSpec(
        kind=kind,
        endpoint="http://target/chat",
        secret_ref="TARGET_KEY",
        declared_capabilities=(),
        safe_mode=True,
        options=options,
        min_interval_seconds=0.25,
    )


def test_the_engine_names_no_concrete_target_adapter() -> None:
    """If it did, a change there would be a way to reach the assistant without the wrapper."""
    for module in (attack, governed):
        source = inspect.getsource(module)
        for forbidden in ("AlquimiaTargetAssistant", "ReplayTargetAssistant"):
            assert forbidden not in source, f"{module.__name__} constructs {forbidden} directly"


def test_every_shipped_kind_comes_out_governed() -> None:
    options: dict[str, dict[str, Any]] = {
        REPLAY: {"responses": {}},
        ALQUIMIA: {"assistant_id": "a"},
    }
    assert set(options) == set(KINDS), "a kind this test does not build could reach the run raw"
    for kind in KINDS:
        built = attackable(_connector(kind, **options[kind]), _Resolver(), budget=Budget())
        assert isinstance(built, GovernedTarget), f"{kind} reached the engine ungoverned"


def test_the_spec_s_interval_and_retries_become_the_door_s() -> None:
    """`RateGate()` built with no arguments would be pacing off however the run was declared."""
    built = attackable(_connector(REPLAY, responses={}), _Resolver(), budget=Budget())
    assert built._rate.min_interval_seconds == 0.25
    assert built._max_retries == 3


def test_the_secret_reference_is_resolved_before_the_first_turn() -> None:
    """Resolution failing here fails the run before anything is sent, which is the right moment."""

    class _Missing:
        def resolve(self, ref: str) -> str:
            raise KeyError(ref)

    with pytest.raises(KeyError, match="TARGET_KEY"):
        attackable(_connector(REPLAY, responses={}), _Missing(), budget=Budget())


def test_an_unknown_kind_is_refused_by_name() -> None:
    from redteam_target import UnknownTarget

    with pytest.raises(UnknownTarget, match="'http'"):
        attackable(_connector("http"), _Resolver(), budget=Budget())
