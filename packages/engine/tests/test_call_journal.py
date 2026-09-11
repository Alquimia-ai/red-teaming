"""The allowance is spent before transport, including failures without a response."""

from __future__ import annotations

import pytest
from gaussia.schemas.roastme import TargetResponse

from redteam_contracts.failure import SERVER_ERROR, TransportFailure
from redteam_engine.call_journal import CallJournal
from redteam_engine.checkpoints import RecoveryIncomplete
from redteam_engine.governed import Budget, BudgetExhausted, GovernedTarget, RateGate
from redteam_store import layout
from redteam_store.memory import MemoryObjectStore
from redteam_target.capabilities import CapabilityGate
from redteam_target.failures import failed_response


def test_uncertain_reservation_remains_consumed_after_restart() -> None:
    store = MemoryObjectStore()
    CallJournal(store, "r", 2).reserve("q", None)
    resumed = CallJournal(store, "r", 2)
    assert resumed.reserve("retry", None) == 2
    with pytest.raises(BudgetExhausted):
        CallJournal(store, "r", 2).reserve("extra", None)


def test_concurrent_reservers_cannot_exceed_the_limit() -> None:
    store = MemoryObjectStore()
    first, second = CallJournal(store, "r", 1), CallJournal(store, "r", 1)
    first.reserve("q", None)
    with pytest.raises(BudgetExhausted):
        second.reserve("other", None)


def test_legacy_attempts_cannot_be_assumed_free() -> None:
    store = MemoryObjectStore()
    for attempt in ("old", "current"):
        store.put(layout.attempt("r", attempt), b"{}")
    with pytest.raises(RecoveryIncomplete, match="unknown"):
        CallJournal(store, "r", 2)


def test_transport_retries_spend_durable_allowance() -> None:
    store = MemoryObjectStore()

    class FailingTarget:
        calls = 0

        def send(self, query: str, session_id: str | None = None) -> TargetResponse:
            self.calls += 1
            return failed_response(
                TransportFailure(kind=SERVER_ERROR, message="down", error_type="server")
            )

    target = FailingTarget()
    for _ in range(2):
        with pytest.raises(BudgetExhausted):
            governed = GovernedTarget(
                target,
                gate=CapabilityGate(declared_capabilities=(), safe_mode=True),
                budget=Budget(journal=CallJournal(store, "r", 2)),
                rate=RateGate(sleep=lambda _: None),
                max_retries=3,
            )
            governed.send("q")
    assert target.calls == 2


def test_failed_reservation_never_reaches_target(monkeypatch: pytest.MonkeyPatch) -> None:
    store = MemoryObjectStore()
    journal = CallJournal(store, "r", 1)

    def fail(key: str, data: bytes, *, content_type: str | None = None) -> None:
        raise OSError("store down")

    monkeypatch.setattr(store, "put", fail)
    with pytest.raises(OSError):
        Budget(journal=journal).charge("q")
    assert journal.calls == 0
