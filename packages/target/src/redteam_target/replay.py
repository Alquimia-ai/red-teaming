"""Recorded answers, through the same interface a live assistant is reached through.

Not a separate mode -- an implementation of the same interface, which is what makes rehearsing a
whole run offline and without credentials the same code path as a live one. The recordings travel in
`ConnectorSpec.options["responses"]`, keyed by query; a query nobody recorded is reported as an
empty answer, never invented.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from gaussia.core.target_assistant import TargetAssistant
from gaussia.schemas.roastme import TargetResponse

from redteam_target.failures import empty_response, failed_response

if TYPE_CHECKING:
    from redteam_contracts.run_spec import ConnectorSpec

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
