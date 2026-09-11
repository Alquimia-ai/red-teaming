"""A run-wide allowance: reserve durably before sending, never refund an uncertain call."""

from __future__ import annotations

import json

from gaussia.schemas.roastme import TargetResponse

from redteam_engine.checkpoints import RecoveryIncomplete, put_same
from redteam_store import layout
from redteam_store.codec import encode_json
from redteam_store.interface import ObjectAlreadyExists, ObjectStore
from redteam_target.failures import failure_of


class CallJournal:
    def __init__(self, store: ObjectStore, run_id: str, limit: int | None) -> None:
        self.store, self.run_id, self.limit = store, run_id, limit
        key = layout.call_budget(run_id)
        if not store.exists(key):
            previous = len(store.list_prefix(layout.attempts_prefix(run_id) + "/")) > 1
            evidence = bool(store.list_prefix(layout.traces_prefix(run_id) + "/"))
            if limit is not None and (previous or evidence):
                raise RecoveryIncomplete(
                    "legacy run has no durable call budget; consumed allowance is unknown; "
                    "preserve the evidence and start a new run"
                )
        put_same(store, key, encode_json({"version": 1, "limit": limit}))
        if store.exists(layout.recovery(run_id, "budget-exhausted")):
            from redteam_engine.governed import BudgetExhausted

            raise BudgetExhausted(f"budget of {limit} target calls exhausted")
        self.calls = sum(
            key.endswith(".reserved.json") for key in store.list_prefix(layout.calls_prefix(run_id))
        )

    def reserve(self, query: str | None, session_id: str | None) -> int:
        from redteam_engine.governed import BudgetExhausted

        while self.limit is None or self.calls < self.limit:
            number = self.calls + 1
            try:
                self.store.put(
                    layout.call_entry(self.run_id, number),
                    encode_json({"query": query, "session_id": session_id}),
                    content_type="application/json",
                )
            except ObjectAlreadyExists:
                self.calls = number
                continue
            self.calls = number
            return number
        put_same(self.store, layout.recovery(self.run_id, "budget-exhausted"), b'{"version":1}')
        raise BudgetExhausted(f"budget of {self.limit} target calls exhausted")

    def responded(self, number: int, response: TargetResponse) -> None:
        failure = failure_of(response)
        put_same(
            self.store,
            layout.call_entry(self.run_id, number, result=True),
            encode_json(
                {
                    "content": response.content,
                    "session_id": response.session_id,
                    "failed": response.failed,
                    "failure_reason": response.failure_reason,
                    "failure": json.loads(failure.model_dump_json())
                    if failure is not None
                    else None,
                }
            ),
        )
