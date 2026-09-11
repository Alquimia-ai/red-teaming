"""One run against a real assistant with a real judge, in process. Skips unless the environment
names both; see README.md."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

pytestmark = pytest.mark.live

ROOT = Path(__file__).resolve().parents[2]
BASELINE = ROOT / "deploy" / "seed" / "catalogues" / "assistant-baseline"
REQUIRED = (
    "LIVE_ASSISTANT_ENDPOINT",
    "LIVE_ASSISTANT_ID",
    "LIVE_TARGET_TOKEN",
    "LIVE_JUDGE_MODEL",
    "LIVE_JUDGE_PROVIDER",
    "LIVE_JUDGE_KEY",
)
ONE_TURN = ["ask-identity", "ask-system-prompt", "act-for-another", "refuse-escalation"]


def _live() -> dict[str, str]:
    missing = [name for name in REQUIRED if not os.environ.get(name)]
    if missing:
        pytest.skip(f"live environment not set: {', '.join(missing)}")
    return {name: os.environ[name] for name in REQUIRED}


def test_a_real_assistant_is_profiled_by_a_real_judge(capsys: pytest.CaptureFixture[str]) -> None:
    from redteam_catalogue import assets
    from redteam_catalogue.bundle import load_bundle
    from redteam_catalogue.engines import declared_engines
    from redteam_contracts.manifest import Manifest, RunPhase
    from redteam_runner import pipeline
    from redteam_secrets.resolver import EnvSecretResolver
    from redteam_settings.config import Settings, StoreBackend
    from redteam_store import layout
    from redteam_store.memory import MemoryObjectStore

    live = _live()
    store = MemoryObjectStore()
    bundle = load_bundle(BASELINE)
    assets.publish(
        store,
        "assistant-baseline",
        bundle.catalogue,
        bundle.contract,
        *declared_engines(bundle.entity_kinds),
        needs_base=sorted(assets.needs_a_base(bundle.catalogue, bundle.needs_base)),
        delivery=bundle.delivery,
    )
    judge: dict[str, Any] = {
        "model": live["LIVE_JUDGE_MODEL"],
        "provider": live["LIVE_JUDGE_PROVIDER"],
        "secret_ref": "LIVE_JUDGE_KEY",
        "self_hosted": live["LIVE_JUDGE_PROVIDER"] == "openai_compatible",
    }
    if os.environ.get("LIVE_JUDGE_ENDPOINT"):
        judge["endpoint"] = os.environ["LIVE_JUDGE_ENDPOINT"]
    options: dict[str, Any] = {"assistant_id": live["LIVE_ASSISTANT_ID"]}
    if os.environ.get("LIVE_ASSISTANT_AGENTSPACE"):
        options["agentspace_id"] = os.environ["LIVE_ASSISTANT_AGENTSPACE"]
    run_id = "redteam-run-live"
    spec = {
        "run_id": run_id,
        "kb_ref": None,
        "catalogues": ["assistant-baseline"],
        "catalogue_versions": {"assistant-baseline": 1},
        "plugins": [],
        "strategies": ONE_TURN,
        "connector": {
            "kind": "alquimia",
            "endpoint": live["LIVE_ASSISTANT_ENDPOINT"],
            "secret_ref": "LIVE_TARGET_TOKEN",
            "options": options,
            "min_interval_seconds": 1.0,
        },
        "judge": judge,
        "context": {"language": "es-419", "domain": "an assistant under evaluation"},
        "replicas": int(os.environ.get("LIVE_REPLICAS", "1")),
        "budget": {"max_wall_seconds": 1800},
    }
    store.put(layout.spec(run_id), json.dumps(spec).encode())

    outcome = pipeline.execute(
        run_id,
        settings=Settings(store_backend=StoreBackend.MEMORY),
        store=store,
        resolver=EnvSecretResolver(),
    )

    assert outcome.phase is RunPhase.COMPLETE, outcome
    manifest = Manifest.model_validate_json(store.get(layout.manifest(run_id)))
    assert manifest.coverage.total.pending == 0
    assert manifest.coverage.total.closed > 0
    assert manifest.components["profile_judge_serving_path"] != "fake", "a real judge graded"
    assert manifest.components["profile_judge_model"] == live["LIVE_JUDGE_MODEL"]
    assert manifest.components["target"] == "alquimia"
    with capsys.disabled():
        print("\ncoverage:", manifest.coverage.model_dump_json(indent=2))
        print("components:", json.dumps(manifest.components, indent=2))
