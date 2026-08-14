"""The data boundary between the red-teaming app and the outside world.

The app consumes a *knowledge bundle* and produces *findings*. It does so through these
ports, with file-backed adapters as the default. Whatever sits on the other side — the
Boltzmann brain, curated by ``braintools``; a fixture; an object store — is not the
app's concern. Nothing here references the brain.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, Field


class Document(BaseModel):
    """One unit of knowledge the probe library reasons over."""

    id: str
    content: str
    structured: bool = False


class KnowledgeBundle(BaseModel):
    """Everything the app needs as input, with no brain semantics attached.

    ``catalogue`` and ``contract`` are carried opaquely (validated downstream by the
    RoastMe pipeline) so this boundary does not couple to gaussia's schema either.
    """

    documents: list[Document] = Field(default_factory=list)
    catalogue: dict[str, Any] | None = None
    contract: dict[str, Any] | None = None


@runtime_checkable
class KnowledgeSource(Protocol):
    """Where the app reads its knowledge bundle from."""

    def load(self) -> KnowledgeBundle: ...


@runtime_checkable
class FindingsSink(Protocol):
    """Where the app writes its findings artifact to."""

    def emit(self, findings: dict[str, Any]) -> None: ...


class FileKnowledgeSource:
    """Reads a knowledge bundle from a JSON file (e.g. a mounted volume/ConfigMap)."""

    def __init__(self, path: Path):
        self.path = Path(path)

    def load(self) -> KnowledgeBundle:
        if not self.path.exists():
            raise FileNotFoundError(f"knowledge bundle not found: {self.path}")
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        return KnowledgeBundle.model_validate(raw)


class FileFindingsSink:
    """Writes a findings artifact to a JSON file (e.g. a mounted output volume)."""

    def __init__(self, path: Path):
        self.path = Path(path)

    def emit(self, findings: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(findings, indent=2, ensure_ascii=False, default=str),
            encoding="utf-8",
        )
