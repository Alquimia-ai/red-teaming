"""Coverage is three numbers a reader can divide; nothing here divides them."""

from __future__ import annotations

from redteam_contracts.manifest import Coverage, CoverageReport, Manifest, RunPhase


def test_pending_is_what_the_plan_still_owes() -> None:
    assert Coverage(planned=10, closed=6, failed=1).pending == 3
    assert Coverage(planned=4, closed=4, failed=0).pending == 0


def test_the_phases_have_no_measuring_step() -> None:
    assert [p.value for p in RunPhase] == [
        "accepted",
        "generating",
        "attacking",
        "complete",
        "failed",
    ]


def test_a_manifest_names_its_control_artifacts_apart_from_its_evidence() -> None:
    manifest = Manifest(
        run_id="run-1",
        phase=RunPhase.COMPLETE,
        spec_digest="sha256:abc",
        dataset="runs/run-1/dataset.json",
        profile="runs/run-1/profile.json",
        exploit=None,
        n_total_traces=12,
        coverage=CoverageReport(total=Coverage(planned=12, closed=12, failed=0)),
        components={"exploit": "not run: no realism prior declared"},
    )
    restored = Manifest.model_validate_json(manifest.model_dump_json())
    assert restored == manifest
    assert restored.exploit is None and restored.coverage.total.pending == 0
