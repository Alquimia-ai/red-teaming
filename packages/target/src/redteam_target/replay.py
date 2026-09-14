"""Replay ConnectorSpec.options responses by query through the target interface.

An unrecorded query returns an empty response. Offline runs use the same orchestration path."""

from __future__ import annotations

from gaussia.core.target_assistant import TargetAssistant
from gaussia.schemas.roastme import TargetResponse

from redteam_contracts.run_spec import ConnectorSpec
from redteam_target.failures import empty_response, failed_response

REPLAY = "replay"


class ReplayTargetAssistant(TargetAssistant):  # type: ignore[misc]  # gaussia ships no stubs
    """Replays recorded responses."""

    def __init__(self, responses: dict[str, str]) -> None:
        self._responses = responses

    def send(self, query: str, session_id: str | None = None) -> TargetResponse:
        if query not in self._responses:
            return failed_response(
                empty_response("no recorded response", error_type="replay"), session_id=session_id
            )
        return TargetResponse(content=self._responses[query], session_id=session_id)


def build_replay(spec: ConnectorSpec, credential: str | None) -> TargetAssistant:
    """Recorded answers, keyed by query, from `options.responses`. No credential and no network."""
    responses = spec.options.get("responses") or {}
    return ReplayTargetAssistant({str(k): str(v) for k, v in dict(responses).items()})
