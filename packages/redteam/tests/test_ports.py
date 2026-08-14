"""Tests for the app's data boundary. No brain, no network, no gaussia."""

from __future__ import annotations

import json

import pytest
from redteam.ports import (
    FileFindingsSink,
    FileKnowledgeSource,
    FindingsSink,
    KnowledgeBundle,
    KnowledgeSource,
)


def test_file_knowledge_source_loads_bundle(tmp_path):
    path = tmp_path / "knowledge.json"
    path.write_text(
        json.dumps(
            {
                "documents": [
                    {"id": "d1", "content": "POLICY-1 covers 30 days.", "structured": False}
                ],
                "catalogue": {"plugins": []},
                "contract": {"principles": []},
            }
        )
    )
    bundle = FileKnowledgeSource(path).load()
    assert isinstance(bundle, KnowledgeBundle)
    assert len(bundle.documents) == 1
    assert bundle.documents[0].id == "d1"
    assert bundle.catalogue == {"plugins": []}
    assert bundle.contract == {"principles": []}


def test_file_knowledge_source_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        FileKnowledgeSource(tmp_path / "nope.json").load()


def test_file_findings_sink_writes_and_creates_dirs(tmp_path):
    out = tmp_path / "nested" / "findings.json"
    FileFindingsSink(out).emit({"failures": [{"category": "invented-entity"}]})
    assert out.exists()
    written = json.loads(out.read_text())
    assert written["failures"][0]["category"] == "invented-entity"


def test_file_adapters_satisfy_the_protocols(tmp_path):
    # Structural typing: the file adapters ARE a KnowledgeSource / FindingsSink.
    assert isinstance(FileKnowledgeSource(tmp_path / "k.json"), KnowledgeSource)
    assert isinstance(FileFindingsSink(tmp_path / "f.json"), FindingsSink)
