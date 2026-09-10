"""A spec's `kind` is read by something, and only the two shipped kinds build an adapter."""

from __future__ import annotations

import pytest

from redteam_contracts.run_spec import ConnectorSpec
from redteam_target import KINDS, UnknownTarget, build_target
from redteam_target.alquimia import ALQUIMIA, AlquimiaTargetAssistant
from redteam_target.capabilities import CapabilityGate, SafeModeViolation
from redteam_target.replay import REPLAY, ReplayTargetAssistant


def _spec(kind: str, **options: object) -> ConnectorSpec:
    return ConnectorSpec(kind=kind, endpoint="http://target", secret_ref="K", options=options)


def test_exactly_two_kinds_exist() -> None:
    assert KINDS == (ALQUIMIA, REPLAY)


def test_each_kind_builds_its_own_transport() -> None:
    assert isinstance(build_target(_spec(ALQUIMIA, assistant_id="a"), "k"), AlquimiaTargetAssistant)
    assert isinstance(build_target(_spec(REPLAY), None), ReplayTargetAssistant)


def test_an_unknown_kind_is_refused_and_names_what_exists() -> None:
    """`kind` has to be read by something: a typo must fail rather than silently reach the wrong
    transport."""
    with pytest.raises(UnknownTarget, match="not-a-transport") as refused:
        build_target(_spec("not-a-transport"), None)
    assert refused.value.kind == "not-a-transport"
    for kind in KINDS:
        assert kind in str(refused.value)


def test_replay_answers_from_the_spec_s_own_recordings_and_invents_nothing() -> None:
    adapter = build_target(_spec(REPLAY, responses={"hi": "recorded"}), None)
    assert adapter.send("hi").content == "recorded"
    unknown = adapter.send("unknown")
    assert unknown.failed and unknown.content == ""
    assert "no recorded response" in str(unknown.failure_reason)


def test_replay_forwards_the_session_it_is_handed() -> None:
    adapter = build_target(_spec(REPLAY, responses={"hi": "recorded"}), None)
    assert adapter.send("hi", session_id="s-1").session_id == "s-1"


def test_the_safe_mode_gate_refuses_an_acting_target_without_a_sandbox() -> None:
    """Not a configuration checkbox: the one place that can refuse to start."""
    CapabilityGate(declared_capabilities=(), safe_mode=False).assert_may_attack()
    CapabilityGate(declared_capabilities=("payments",), safe_mode=True).assert_may_attack()
    with pytest.raises(SafeModeViolation, match="payments"):
        CapabilityGate(declared_capabilities=("payments",), safe_mode=False).assert_may_attack()
