"""One store per test, a dispatcher that records rather than launches, and the seed bundle
published: what every route test starts from."""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from redteam_api import deps
from redteam_api.main import app
from redteam_catalogue import assets
from redteam_catalogue.bundle import load_bundle
from redteam_dispatch import JobHandle, JobState
from redteam_store.memory import MemoryObjectStore

ROOT = Path(__file__).resolve().parents[3]
BASELINE = ROOT / "deploy" / "seed" / "catalogues" / "assistant-baseline"
CATALOGUE = "assistant-baseline"


class RecordingDispatcher:
    """Remembers every launch and answers the liveness a test sets."""

    def __init__(self) -> None:
        self.launched: list[tuple[str, tuple[str, ...]]] = []
        self.states: dict[str, JobState] = {}

    def launch(
        self,
        run_id: str,
        *,
        env: Mapping[str, str] | None = None,
        secret_refs: Sequence[str] = (),
    ) -> JobHandle:
        self.launched.append((run_id, tuple(secret_refs)))
        self.states[run_id] = JobState.RUNNING
        return JobHandle(run_id=run_id, backend="recording", identifier=run_id)

    def status(self, run_id: str) -> JobState:
        return self.states.get(run_id, JobState.UNKNOWN)


def publish_baseline(store: MemoryObjectStore, name: str = CATALOGUE) -> int:
    bundle = load_bundle(BASELINE)
    document = bundle.document.model_copy(update={"name": name})
    published = assets.publish_document(store, document)
    return published.version


@pytest.fixture
def store(monkeypatch: pytest.MonkeyPatch) -> MemoryObjectStore:
    fresh = MemoryObjectStore()
    deps.settings.cache_clear()
    deps.store.cache_clear()
    deps.resolver.cache_clear()
    deps.dispatcher.cache_clear()
    monkeypatch.setattr(deps, "store", lambda: fresh)
    return fresh


@pytest.fixture
def dispatcher(store: MemoryObjectStore, monkeypatch: pytest.MonkeyPatch) -> RecordingDispatcher:
    recording = RecordingDispatcher()
    monkeypatch.setattr(deps, "dispatcher", lambda: recording)
    return recording


@pytest.fixture
def client(
    store: MemoryObjectStore, dispatcher: RecordingDispatcher, monkeypatch: pytest.MonkeyPatch
) -> Iterator[TestClient]:
    monkeypatch.setenv("TARGET_KEY", "the-target-credential")
    publish_baseline(store)
    with TestClient(app) as test_client:
        yield test_client
