"""App settings, resolved from environment. Agent endpoint plus the two boundary paths.
No brain settings live here — the app does not know the brain exists.
"""

from __future__ import annotations

import os
from pathlib import Path

# The Alquimia agent under test (TargetAssistant adapter).
AGENT_BASE_URL_ENV = "ALQUIMIA_AGENT_BASE_URL"
AGENT_TOKEN_ENV = "ALQUIMIA_AGENT_TOKEN"

# The data boundary: knowledge in, findings out (files/volumes).
KNOWLEDGE_PATH_ENV = "REDTEAM_KNOWLEDGE_PATH"
FINDINGS_PATH_ENV = "REDTEAM_FINDINGS_PATH"
DEFAULT_KNOWLEDGE_PATH = "data/knowledge.json"
DEFAULT_FINDINGS_PATH = "data/findings.json"


def agent_base_url() -> str | None:
    return os.environ.get(AGENT_BASE_URL_ENV)


def agent_token() -> str | None:
    return os.environ.get(AGENT_TOKEN_ENV)


def knowledge_path() -> Path:
    return Path(os.environ.get(KNOWLEDGE_PATH_ENV, DEFAULT_KNOWLEDGE_PATH)).resolve()


def findings_path() -> Path:
    return Path(os.environ.get(FINDINGS_PATH_ENV, DEFAULT_FINDINGS_PATH)).resolve()
