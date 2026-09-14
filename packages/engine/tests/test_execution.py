"""Identity survives replicas, replay and the actual Gaussia profiling adapter."""

from collections.abc import Sequence
from contextlib import suppress
from typing import Any

import pytest
from gaussia.generators.roastme.profiler import Profiler
from gaussia.schemas.roastme import BehavioralContract, Principle, Probe, TargetResponse

from redteam_contracts.plan import WorkUnit
from redteam_engine.dataset import roast_dataset
from redteam_engine.execution import PlanProfiler, ProfileOrderError, key_of
from redteam_engine.governed import Budget, GovernedTarget
from redteam_engine.planned import PlannedDelivery
from redteam_engine.recording import Recorder
from redteam_judges.fake import FakeGrader
from redteam_store import layout
from redteam_store.codec import decode_trace
from redteam_store.delivery import STATIC
from redteam_store.memory import MemoryObjectStore
from redteam_target.capabilities import CapabilityGate


class Target:
    def __init__(self) -> None:
        self.calls = 0

    def send(self, query: str, session_id: str | None = None) -> TargetResponse:
        self.calls += 1
        return TargetResponse(content=f"answer-{self.calls}")


def setup(
    *, mode: str = "normal", replay: bool = False
) -> tuple[PlanProfiler, Target, Budget, MemoryObjectStore]:
    probe = Probe(
        id="same", query="identical question", strategy="s", attrs=["asks a question"], plugin="p"
    )
    units = [WorkUnit(probe_id=probe.id, replica_idx=i, plugin="p", strategy="s") for i in range(3)]
    store = MemoryObjectStore()
    recorder = Recorder(store, "r", {probe.id: probe.model_dump()})
    recorded = {key_of(units[0]): TargetResponse(content="earlier answer")} if replay else {}
    if replay:
        recorder.record(units[0], probe.query, recorded[key_of(units[0])])
    # Failure evidence is not completion: the middle unit must still go live.
    store.put(layout.trace_failure("r", units[1].attack_id, 1), b"earlier failure")
    budget = Budget()
    target = Target()
    governed = GovernedTarget(
        target,
        gate=CapabilityGate(declared_capabilities=(), safe_mode=True),
        budget=budget,
        on_exchange=recorder,
    )
    contract = BehavioralContract(
        principles=[Principle(id="p", weight=1.0, rubric="rule", grader=FakeGrader())]
    )

    class SelectedProfiler:
        def __init__(self, target: Any) -> None:
            self.target = target

        def profile(self, probes: Sequence[Probe]) -> Any:
            if mode == "reorder":
                self.target.send("unexpected query")
            result = Profiler(contract, self.target).profile(probes)
            if mode == "missing":
                result.outcomes.pop()
            elif mode == "wrong_id":
                result.outcomes[0].probe_id = "other"
            elif mode == "extra":
                with suppress(ProfileOrderError):
                    self.target.send("extra query")
            return result

    adapter = PlanProfiler(
        units,
        {probe.id: probe},
        recorded,
        {key_of(unit): PlannedDelivery(STATIC, None) for unit in units},
        governed,
        recorder,
        SelectedProfiler,
    )
    return adapter, target, budget, store


@pytest.mark.parametrize("replay", [False, True])
def test_replica_results_keep_identity_even_when_assembled_in_reverse(replay: bool) -> None:
    adapter, target, budget, store = setup(replay=replay)
    adapter.profile(adapter.probes)
    expected = (
        ["earlier answer", "answer-1", "answer-2"]
        if replay
        else ["answer-1", "answer-2", "answer-3"]
    )
    assert target.calls == budget.calls == (2 if replay else 3)
    assert adapter.replayed == int(replay)
    datasets = roast_dataset(
        list(reversed(adapter.outcomes)),
        None,
        run_id="r",
        assistant_id="a",
        context="c",
        language="es",
    )
    assert [session.conversation[0].assistant for session in datasets.sessions] == expected
    for item, response in zip(adapter.outcomes, expected, strict=True):
        trace = decode_trace(
            store.get(layout.trace("r", item.unit.attack_id, item.unit.replica_idx))
        )
        assert trace.agent_turns[-1].content == response


@pytest.mark.parametrize("mode", ["missing", "wrong_id", "extra", "reorder"])
def test_profiler_contract_violation_cannot_produce_identified_results(mode: str) -> None:
    adapter, _, _, _ = setup(mode=mode)
    with pytest.raises(ProfileOrderError):
        adapter.profile(adapter.probes)
    assert adapter.outcomes == ()


def test_profile_target_cannot_be_used_for_exploitation() -> None:
    adapter, target, _, _ = setup()
    with pytest.raises(ProfileOrderError):
        adapter.send("unplanned")
    assert target.calls == 0
