"""Wait for a hosted OpenAI-compatible judge before spending a run's conversations."""

from __future__ import annotations

import time
from collections.abc import Callable

import httpx

from redteam_contracts.run_spec import ModelSpec
from redteam_judges.models import OPENAI_COMPATIBLE

DEFAULT_MAX_WAIT_SECONDS = 600
DEFAULT_INTERVAL_SECONDS = 5
REQUEST_TIMEOUT_SECONDS = 10
RETRYABLE_STATUSES = {502, 503, 504}


class JudgeNotReady(RuntimeError):
    """The judge did not become available before its readiness deadline."""


def wait_for_judge(
    spec: ModelSpec,
    api_key: str | None,
    *,
    cancelled: Callable[[], bool],
    max_wait_seconds: float = DEFAULT_MAX_WAIT_SECONDS,
    interval_seconds: float = DEFAULT_INTERVAL_SECONDS,
    transport: httpx.BaseTransport | None = None,
) -> bool:
    """Return false if cancelled; fail before attacking if a hosted judge stays unavailable."""
    if spec.provider != OPENAI_COMPATIBLE or spec.self_hosted or spec.endpoint is None:
        return True

    deadline = time.monotonic() + max_wait_seconds
    url = f"{spec.endpoint.rstrip('/')}/models"
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    with httpx.Client(timeout=REQUEST_TIMEOUT_SECONDS, transport=transport) as client:
        while not cancelled():
            try:
                response = client.get(url, headers=headers)
            except httpx.RequestError as failed:
                last = type(failed).__name__
            else:
                if response.status_code == 200:
                    return not cancelled()
                if response.status_code not in RETRYABLE_STATUSES:
                    raise JudgeNotReady(
                        f"judge readiness check returned HTTP {response.status_code}"
                    )
                last = f"HTTP {response.status_code}"

            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise JudgeNotReady(
                    f"judge did not become ready within {max_wait_seconds:g}s (last: {last})"
                )
            time.sleep(min(interval_seconds, remaining))
    return False
