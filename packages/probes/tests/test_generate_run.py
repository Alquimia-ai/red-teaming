"""One run's probe set: generated once, addressed by content, pinned by the run's own record."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from gaussia.schemas.roastme import Catalogue, Probe

from redteam_catalogue import assets
from redteam_catalogue.bundle import Bundle, load_bundle
from redteam_catalogue.memory_kb import MemoryKnowledgeBase
from redteam_contracts.kb import BrainRef, Entity, Passage
from redteam_probes.generate import digest_of
from redteam_probes.generate_run import (
    MISSING,
    REFUSED,
    UNKNOWN,
    UPSTREAM,
    classify,
    existing_report,
    generate_for,
)
from redteam_probes.request import GenerationRequest
from redteam_store import contract as contract_store
from redteam_store import layout
from redteam_store.codec import encode_json
from redteam_store.memory import MemoryObjectStore

ROOT = Path(__file__).resolve().parents[3]
BASELINE = ROOT / "deploy" / "seed" / "catalogues" / "assistant-baseline"

GROUNDED_KB = BrainRef(registry="ghcr.io", repository="acme/kb", digest="sha256:" + "b" * 64)
"""A reference the gate accepts, standing for whatever base a test hands in."""

ATTESTED: tuple[tuple[str, str], ...] = (
    ("product", "Cuenta Digital Libre"),
    ("product", "Pago de Nominas"),
    ("fact", "Cuenta Digital Libre tiene un limite de RD$1.500,00"),
    ("fact", "Pago de Nominas cuesta RD$9.900,00"),
)

BRAINLESS = (
    "ask-identity",
    "ask-system-prompt",
    "escalate-system-prompt",
    "act-for-another",
    "refuse-escalation",
)


def _base(fixture: tuple[tuple[str, str], ...]) -> MemoryKnowledgeBase:
    blocks = [f"sha256:{index}" for index, _ in enumerate(fixture)]
    return MemoryKnowledgeBase(
        [
            Entity(kind=kind, name=name, block_id=block)
            for (kind, name), block in zip(fixture, blocks, strict=True)
        ],
        [
            Passage(id=block, content=name, structured=True, kind=kind)
            for (kind, name), block in zip(fixture, blocks, strict=True)
        ],
    )


def _publish(
    store: MemoryObjectStore, name: str, bundle: Bundle, catalogue: Catalogue | None = None
) -> None:
    document = bundle.document_for(catalogue) if catalogue is not None else bundle.document
    assets.publish_document(store, document.model_copy(update={"name": name}))


@pytest.fixture
def bundle() -> Bundle:
    return load_bundle(BASELINE)


@pytest.fixture
def store(bundle: Bundle) -> MemoryObjectStore:
    store = MemoryObjectStore()
    _publish(store, "baseline", bundle)
    return store


def _request(run_id: str, **overrides: Any) -> GenerationRequest:
    fields: dict[str, Any] = {
        "run_id": run_id,
        "catalogues": ("baseline",),
        "strategies": () if overrides.get("brain") is not None else BRAINLESS,
    }
    fields.update(overrides)
    return GenerationRequest.model_validate(fields)


def test_a_brainless_run_generates_the_standing_half_and_cites_nothing(
    store: MemoryObjectStore, bundle: Bundle
) -> None:
    report = generate_for(store, _request("run-report"))

    assert report.probe_count > 0 and report.probes_digest
    assert report.grounded is False, "the set has to say it was built against no base"
    assert report.engines_ran == ("enumeration",)
    assert report.degenerate_strategies == () and report.unverified_probes == ()
    assert report.unresolved_entities == {}, "no base, so no entity to deform"
    assert report.strategies_set_aside == ()
    assert report.catalogue_versions == {"baseline": 1}
    assert report.contract_digest == contract_store.digest(store, "baseline", 1)

    probes = json.loads(store.get(layout.blob(report.probes_digest)))
    hints = {s.phrasing_hint for s in bundle.catalogue.strategies}
    for probe in probes:
        assert probe["query"] in hints, f"{probe['query']!r} is not a phrasing anybody wrote"
        assert probe["hook"] is None and "block_id" not in probe["meta"]


def test_the_second_run_over_one_set_skips_the_write_and_the_first_does_not(
    store: MemoryObjectStore,
) -> None:
    """Both halves asserted: a flag whose job is to say "this cost nothing" must not say it for the
    run that wrote the blob."""
    first = generate_for(store, _request("run-a"))
    second = generate_for(store, _request("run-b"))

    assert first.probes_digest == second.probes_digest
    assert first.skipped_existing is False
    assert second.skipped_existing is True


def test_a_run_whose_set_is_pinned_is_answered_from_its_record(
    store: MemoryObjectStore, bundle: Bundle
) -> None:
    """A catalogue published between two launches of one run must not change the plan."""
    first = generate_for(store, _request("run-pinned"))

    revised = bundle.catalogue.model_copy(
        update={
            "strategies": [
                s.model_copy(update={"id": f"{s.id}-v2"}) if s.id == "ask-identity" else s
                for s in bundle.catalogue.strategies
            ]
        }
    )
    _publish(store, "baseline", bundle, revised)
    again = generate_for(store, _request("run-pinned"))
    fresh = generate_for(store, _request("run-after-v2"))

    assert again.probes_digest == first.probes_digest
    assert again.skipped_existing is True
    assert again.catalogue_versions == {"baseline": 1}
    assert fresh.probes_digest != first.probes_digest, "v2 changed nothing; the test is moot"
    assert fresh.catalogue_versions == {"baseline": 2}


def test_a_pointer_written_before_it_carried_a_report_still_pins_the_run(
    store: MemoryObjectStore,
) -> None:
    store.put(
        layout.probes("run-old-pointer"),
        encode_json({"digest": "f" * 64, "count": 7}),
        content_type="application/json",
    )
    report = existing_report(store, "run-old-pointer")
    assert report is not None
    assert (report.probes_digest, report.probe_count, report.skipped_existing) == (
        "f" * 64,
        7,
        True,
    )
    assert generate_for(store, _request("run-old-pointer")) == report
    assert existing_report(store, "run-never") is None


def test_a_frozen_version_is_generated_from_even_after_a_newer_one_is_published(
    store: MemoryObjectStore, bundle: Bundle
) -> None:
    v1 = generate_for(store, _request("run-frozen-a"))
    revised = bundle.catalogue.model_copy(
        update={
            "strategies": [
                s.model_copy(update={"id": f"{s.id}-v2"}) if s.id == "ask-scope" else s
                for s in bundle.catalogue.strategies
            ]
        }
    )
    _publish(store, "baseline", bundle, revised)

    pinned = generate_for(store, _request("run-frozen-b", catalogue_versions={"baseline": 1}))

    assert pinned.probes_digest == v1.probes_digest
    assert json.loads(store.get(layout.probes("run-frozen-b")))["digest"] == v1.probes_digest


def test_a_grounded_run_is_addressed_by_the_digest_the_library_computes(
    store: MemoryObjectStore,
) -> None:
    """One artifact, one identity: hash what is there, get the key it is under."""
    report = generate_for(
        store, _request("run-addressed", brain=GROUNDED_KB), knowledge_base=_base(ATTESTED)
    )

    assert report.grounded is True
    stored = json.loads(store.get(layout.blob(report.probes_digest)))
    assert digest_of([Probe.model_validate(p) for p in stored]) == report.probes_digest
    assert json.loads(store.get(layout.probes("run-addressed")))["digest"] == report.probes_digest
    grounded = [p for p in stored if p["meta"]["requires_brain"]]
    independent = [p for p in stored if not p["meta"]["requires_brain"]]
    assert grounded and all(p["meta"].get("block_id") for p in grounded)
    assert independent and all(p["hook"] is None for p in independent)
    assert report.brain_digest == GROUNDED_KB.digest


def _swap_token_over(store: MemoryObjectStore, bundle: Bundle, name: str, kind: str) -> None:
    """The baseline with its one `swap_token` strategy pointed at `kind` and renamed: a probe's
    identity carries the strategy id, so two catalogues keeping the id would collide instead of
    merging."""
    renamed = f"ask-about-fake-{kind}"
    catalogue = bundle.catalogue.model_copy(
        update={
            "strategies": [
                s.model_copy(update={"id": renamed, "entity_kind": kind})
                if s.id == "ask-about-fake-product"
                else s
                for s in bundle.catalogue.strategies
            ]
        }
    )
    _publish(store, name, bundle, catalogue)


def test_every_catalogue_reports_what_its_constructions_could_not_deform(
    store: MemoryObjectStore, bundle: Bundle
) -> None:
    """One construction named by two catalogues reports both catalogues' entities: `unresolved`
    joins rather than overwrites."""
    _swap_token_over(store, bundle, "swap-product", "product")
    _swap_token_over(store, bundle, "swap-fact", "fact")

    report = generate_for(
        store,
        _request("run-two", brain=GROUNDED_KB, catalogues=("swap-product", "swap-fact")),
        knowledge_base=_base(ATTESTED),
    )

    found = set(report.unresolved_entities["swap_token"])
    assert "Pago de Nominas" in found, "the product catalogue's report survived the merge"
    assert "Pago de Nominas cuesta RD$9.900,00" in found, "and so did the fact catalogue's"


def test_the_order_the_catalogues_are_named_in_does_not_change_the_set_s_address(
    store: MemoryObjectStore, bundle: Bundle
) -> None:
    _swap_token_over(store, bundle, "order-a", "product")
    _swap_token_over(store, bundle, "order-b", "fact")

    forwards = generate_for(
        store,
        _request("run-order-1", brain=GROUNDED_KB, catalogues=("order-a", "order-b")),
        knowledge_base=_base(ATTESTED),
    )
    backwards = generate_for(
        store,
        _request("run-order-2", brain=GROUNDED_KB, catalogues=("order-b", "order-a")),
        knowledge_base=_base(ATTESTED),
    )

    assert forwards.probes_digest == backwards.probes_digest
    assert backwards.skipped_existing is True, "the same set is written once"
    ids = [p["id"] for p in json.loads(store.get(layout.blob(forwards.probes_digest)))]
    assert ids == sorted(ids), "the bytes under a content address are a property of the content"


def test_catalogues_that_disagree_on_the_contract_are_refused(
    store: MemoryObjectStore, bundle: Bundle
) -> None:
    """A run grades against one contract; two catalogues that disagree cannot be graded together
    without somebody choosing, and that choice is not made in silence."""
    from redteam_contracts.contract import parse_contract_spec

    revised = parse_contract_spec(
        json.dumps(
            {
                "version": "other",
                "verdict": {"positive": ["YES"], "negative": ["NO"]},
                "principles": [
                    {"id": p.id, "weight": p.weight, "rubric": p.rubric}
                    for p in bundle.contract.principles
                ],
            }
        )
    )
    from redteam_contracts.contract import as_raw

    other = Bundle(bundle.document.model_copy(update={"contract": as_raw(revised)}))
    _publish(store, "other", other)

    with pytest.raises(contract_store.ContractMismatch):
        generate_for(store, _request("run-mismatch", catalogues=("baseline", "other")))
    assert existing_report(store, "run-mismatch") is None, "a refused run pins nothing"


def test_a_grounded_request_with_nothing_to_pull_through_is_refused(
    store: MemoryObjectStore,
) -> None:
    with pytest.raises(ValueError, match="registry client"):
        generate_for(store, _request("run-x", brain=GROUNDED_KB))


def test_a_supplied_brain_is_not_pulled_when_the_selection_does_not_need_it(
    store: MemoryObjectStore,
) -> None:
    report = generate_for(
        store,
        _request("run-unused-brain", brain=GROUNDED_KB, strategies=BRAINLESS),
    )

    assert report.grounded is False
    assert report.brain_digest is None


def test_failures_are_classified_by_what_the_reader_can_do_about_them() -> None:
    from redteam_catalogue.assets import CatalogueNotFound
    from redteam_catalogue.premises import ContextRequired

    assert classify(ContextRequired("contextual_sibling", "context")) == REFUSED
    assert classify(ValueError("plugins name principles the contract does not carry")) == REFUSED
    assert classify(CatalogueNotFound("nobody")) == MISSING
    assert classify(contract_store.ContractMissing("c", 1)) == MISSING
    assert classify(ConnectionError("registry down")) == UPSTREAM
    assert classify(RuntimeError("a bug")) == UNKNOWN
