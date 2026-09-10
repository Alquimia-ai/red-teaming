"""A trace round-trips through its compressed line format, meta first."""

from __future__ import annotations

from redteam_contracts.failure import RATE_LIMITED, TransportFailure
from redteam_contracts.trace import Role, Trace, TraceLabels, Turn
from redteam_store import codec


def test_a_trace_round_trips() -> None:
    trace = Trace(
        trace_id="t1",
        run_id="run-1",
        attack_id="a" * 32,
        replica_idx=1,
        probe_id="p1",
        turns=(
            Turn(idx=0, role=Role.ATTACKER, content="¿Qué cubre la póliza Delta?"),
            Turn(idx=1, role=Role.AGENT, content="No existe esa póliza."),
            Turn(
                idx=2,
                role=Role.AGENT,
                content="",
                failed=True,
                failure_reason="rate_limited: HTTP 429",
                failure=TransportFailure(
                    kind=RATE_LIMITED, message="slow down", error_type="HTTPStatusError", status=429
                ),
            ),
        ),
        labels=TraceLabels(
            orchestration_technique="many",
            turn_depth=2,
            plugin="invented-entity",
            principle="no_invention",
        ),
    )
    encoded = codec.encode_trace(trace)

    assert codec.decode_trace(encoded) == trace
    lines = list(codec.decode_jsonl(encoded))
    assert "_meta" in lines[0] and len(lines) == 4
    assert trace.has_ungraded_turns and len(trace.agent_turns) == 2
