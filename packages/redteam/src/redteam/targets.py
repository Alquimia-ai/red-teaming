"""TargetAssistant adapter for Alquimia agents under test.

The agent is a **black box** reached only over HTTP. This module keeps the transport
here so the rest of the system talks to an interface, not an endpoint.

For the `roast` roadmap, ``AlquimiaAgentTarget`` is shaped to satisfy gaussia's
``TargetAssistant`` interface (``send(query) -> response | failed``). It deliberately
does NOT import gaussia at module load — that dependency lives behind the `roast`
extra — so the app's base install stays light.
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx

from . import config


@dataclass(frozen=True)
class AgentReply:
    """One exchange with the target. ``failed`` marks a transport/agent error."""

    text: str
    failed: bool = False
    status_code: int | None = None


class AlquimiaAgentTarget:
    """Sends queries to an Alquimia agent over HTTP.

    Base URL and auth come from the environment (``ALQUIMIA_AGENT_BASE_URL`` /
    ``ALQUIMIA_AGENT_TOKEN``) unless passed explicitly. Endpoint shape is intentionally
    minimal here; wire it to the real alquimia-core/runtime contract when building
    `redteam roast`.
    """

    def __init__(
        self,
        base_url: str | None = None,
        token: str | None = None,
        *,
        path: str = "/chat",
        timeout: float = 60.0,
    ):
        self.base_url = base_url or config.agent_base_url()
        self.token = token or config.agent_token()
        self.path = path
        self.timeout = timeout
        if not self.base_url:
            raise ValueError(
                f"No agent base URL. Set {config.AGENT_BASE_URL_ENV} or pass base_url."
            )

    def _headers(self) -> dict[str, str]:
        headers = {"content-type": "application/json"}
        if self.token:
            headers["authorization"] = f"Bearer {self.token}"
        return headers

    def send(self, query: str) -> AgentReply:
        """Send one query; return the reply or a failed exchange."""
        url = self.base_url.rstrip("/") + self.path
        try:
            resp = httpx.post(
                url,
                json={"message": query},
                headers=self._headers(),
                timeout=self.timeout,
            )
        except httpx.HTTPError:
            return AgentReply(text="", failed=True)
        if resp.status_code >= 400:
            return AgentReply(text=resp.text, failed=True, status_code=resp.status_code)
        # Best-effort extraction; adjust to the real agent response schema.
        try:
            body = resp.json()
            text = body.get("message") or body.get("response") or resp.text
        except ValueError:
            text = resp.text
        return AgentReply(text=text, failed=False, status_code=resp.status_code)
