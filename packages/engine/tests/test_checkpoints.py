"""Recovery never substitutes absent evidence with an empty successful result."""

from __future__ import annotations

import pytest
from gaussia.schemas.roastme import RoastBatch, RoastDatasetRecord

from redteam_engine.checkpoints import RecoveryIncomplete
from redteam_engine.dataset import RoastDataset
from redteam_engine.resume import remember_exploit, remembered_exploit
from redteam_store import layout
from redteam_store.memory import MemoryObjectStore


@pytest.mark.parametrize("broken", [layout.session("r", "exploit"), layout.searched("r")])
def test_session_projection_failure_is_recovered_without_searching(
    monkeypatch: pytest.MonkeyPatch,
    broken: str,
) -> None:
    store = MemoryObjectStore()
    session = RoastDataset(
        session_id="r:exploit",
        assistant_id="a",
        context="c",
        language="en",
        conversation=[
            RoastBatch(
                qa_id="q",
                query="question",
                assistant="answer",
                ground_truth_assistant="",
                roast=RoastDatasetRecord(
                    query="question",
                    response="answer",
                    violation=1.0,
                    principles_charged=["p"],
                    rationale=[],
                    evidence="answer",
                ),
            )
        ],
    )
    original = store.put

    def fail(key: str, data: bytes, *, content_type: str | None = None) -> None:
        if key == broken:
            raise OSError("session unavailable")
        original(key, data, content_type=content_type)

    monkeypatch.setattr(store, "put", fail)
    with pytest.raises(OSError):
        remember_exploit(store, "r", {"exploit": "ran"}, [session])
    assert not store.exists(layout.searched("r"))
    monkeypatch.setattr(store, "put", original)
    assert remembered_exploit(store, "r") == ({"exploit": "ran"}, [session])
    assert store.exists(layout.searched("r"))
    assert remembered_exploit(store, "r") == ({"exploit": "ran"}, [session])


def test_empty_search_has_an_explicit_durable_empty_result() -> None:
    store = MemoryObjectStore()
    remember_exploit(store, "r", {"exploit": "ran"}, [])
    assert remembered_exploit(store, "r") == ({"exploit": "ran"}, [])


@pytest.mark.parametrize("key", [layout.searched("r"), layout.recovery("r", "exploit-started")])
def test_missing_search_evidence_blocks_recovery(key: str) -> None:
    store = MemoryObjectStore()
    store.put(key, b'{"components":{"exploit":"ran"}}')
    with pytest.raises(RecoveryIncomplete):
        remembered_exploit(store, "r")


def test_conflicting_projection_cannot_be_committed() -> None:
    store = MemoryObjectStore()
    store.put(layout.searched("r"), b'{"components":{"exploit":"different"}}')
    with pytest.raises(RecoveryIncomplete):
        remember_exploit(store, "r", {"exploit": "ran"}, [])
