"""The sequential Gaussia adapter owns the only positional work-unit association."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence

from gaussia.core.target_assistant import TargetAssistant
from gaussia.schemas.roastme import Probe, ProfilerResult, TargetResponse

from redteam_contracts.plan import WorkUnit
from redteam_engine.conduct import Profiler
from redteam_engine.governed import GovernedTarget
from redteam_engine.outcomes import UnitOutcome
from redteam_engine.planned import PlannedDelivery
from redteam_engine.recording import Recorder

UnitKey = tuple[str, int]


def key_of(unit: WorkUnit) -> UnitKey:
    return unit.attack_id, unit.replica_idx


class ProfileOrderError(RuntimeError):
    """The profiler violated the sequential adapter contract."""


class PlanProfiler(TargetAssistant):  # type: ignore[misc]  # gaussia ships no stubs
    """Profile the whole plan, replaying completed units without charging or recording them."""

    def __init__(
        self,
        units: Sequence[WorkUnit],
        probes: Mapping[str, Probe],
        recorded: Mapping[UnitKey, TargetResponse],
        deliveries: Mapping[UnitKey, PlannedDelivery],
        target: GovernedTarget,
        recorder: Recorder,
        build: Callable[[TargetAssistant], Profiler],
    ) -> None:
        self._units = tuple(units)
        if len({key_of(unit) for unit in units}) != len(units):
            raise ProfileOrderError("duplicate work-unit identity")
        self.probes = [probes[unit.probe_id] for unit in units]
        self._recorded = recorded
        self._deliveries = deliveries
        self._target = target
        self._recorder = recorder
        self._build = build
        self._cursor = 0
        self._active = False
        self._order_error: ProfileOrderError | None = None
        self.replayed = 0
        self.outcomes: tuple[UnitOutcome, ...] = ()

    def profile(self, probes: Sequence[Probe]) -> ProfilerResult:
        if self._active or list(probes) != self.probes:
            raise ProfileOrderError("profile must use the adapter's complete ordered probe list")
        self._cursor = 0
        self._order_error = None
        self.replayed = 0
        self.outcomes = ()
        self._active = True
        try:
            result = self._build(self).profile(self.probes)
            if self._order_error is not None:
                raise self._order_error
            if self._target.fatal is not None:
                raise self._target.fatal
            if self._cursor != len(self._units) or len(result.outcomes) != len(self._units):
                raise ProfileOrderError("profiler did not return one exchange per work unit")
            identified = []
            for unit, probe, outcome in zip(self._units, self.probes, result.outcomes, strict=True):
                if outcome.probe_id != probe.id:
                    raise ProfileOrderError("profiler outcome does not match the expected probe")
                identified.append(UnitOutcome(unit, probe, outcome))
            self.outcomes = tuple(identified)
            return result
        finally:
            self._active = False

    def send(self, query: str, session_id: str | None = None) -> TargetResponse:
        try:
            return self._send(query, session_id)
        except ProfileOrderError as failed:
            self._order_error = failed
            raise

    def _send(self, query: str, session_id: str | None) -> TargetResponse:
        if not self._active or self._cursor >= len(self._units):
            raise ProfileOrderError("unexpected profiler exchange")
        unit = self._units[self._cursor]
        if query != self.probes[self._cursor].query:
            raise ProfileOrderError("profiler changed probe order")
        self._cursor += 1
        key = key_of(unit)
        if key in self._recorded:
            self.replayed += 1
            return self._recorded[key]
        return self._target.send_planned(
            query,
            self._deliveries[key],
            lambda q, r, c: self._recorder.record(unit, q, r, c),
            session_id,
        )
