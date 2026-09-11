"""Probes anchored in a base, with honest labels."""

from __future__ import annotations

from pathlib import Path

import pytest
from gaussia.generators.roastme.probes.verification import collision
from gaussia.schemas.roastme import BehavioralContract, Catalogue

from redteam_catalogue.assets import generatable, needs_a_base
from redteam_catalogue.bundle import load_bundle
from redteam_catalogue.contract import validation_contract
from redteam_catalogue.memory_kb import MemoryKnowledgeBase
from redteam_contracts.kb import Entity, Passage
from redteam_probes.generate import generate

ROOT = Path(__file__).resolve().parents[3]
BASELINE = ROOT / "deploy" / "seed" / "catalogues" / "assistant-baseline"


@pytest.fixture
def catalogue() -> Catalogue:
    return load_bundle(BASELINE).catalogue


@pytest.fixture
def contract() -> BehavioralContract:
    """The bundle's contract, for the tests that need the six rejections to actually run.

    `generate` skips validation when handed no contract, which is why the rest of this file passes
    one nowhere: it is testing what generation produces rather than what it refuses.
    """
    return validation_contract(load_bundle(BASELINE).contract)


FIXTURE: tuple[tuple[str, str], ...] = (
    ("product", "Cuenta Ahorro Futuro Digital"),
    ("product", "Cuenta Corriente Empresarial"),
    ("product", "Cuenta Digital Libre"),
    ("product", "Pago de Nominas"),
    ("fact", "Cuenta Digital Libre tiene un limite de RD$1.500,00"),
    ("fact", "La renovacion vence el 12/03/2026"),
)
"""The test's own base, and **only** the test's.

What a run with no brain generates from is an empty base, and the catalogue's own phrasings say
which strategies can run against one; an invented corpus standing in for a client's would ask a
real assistant about products that do not exist and cite block ids this repo made up.

Kept in Spanish because the near-miss thresholds it exercises were calibrated on Spanish short
names, so renaming these would change what the near-miss test measures for reasons that have
nothing to do with the fixture's home.
"""


def _kb(fixture: tuple[tuple[str, str], ...]) -> MemoryKnowledgeBase:
    """A base that can be enumerated, which is what an engine deciding absence needs.

    The passages carry `structured=True` because these blocks are the enumerable ones. Without at
    least one, the shared engine flow returns probes with no hook and the run measures black-box
    behaviour while reporting itself as knowledge-grounded.
    """
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


@pytest.fixture
def kb() -> MemoryKnowledgeBase:
    """A naming scheme with a gap in it.

    `swap_token` can only invent where the corpus leaves a combination unwritten, so a fixture with
    every combination present would exercise the reporting path and never the construction.
    `Pago de Nominas` is the one with no gap around it, on purpose.
    """
    return _kb(FIXTURE)


def _only_grounded(catalogue: Catalogue) -> Catalogue:
    """The half of a catalogue a run with a base generates from."""
    return generatable(catalogue, grounded=True, name="assistant-baseline")


def test_every_probe_is_citable_to_the_block_it_came_from(
    catalogue: Catalogue, kb: MemoryKnowledgeBase
) -> None:
    """What separates this from red teaming that judges against another model's opinion."""
    probes = generate(_only_grounded(catalogue), kb).probes
    assert probes
    for probe in probes:
        assert probe.meta.get("block_id"), f"{probe.id} cannot be traced to a block"


def test_a_fake_entity_is_labelled_absent_and_a_real_one_present(
    catalogue: Catalogue, kb: MemoryKnowledgeBase
) -> None:
    by_strategy: dict[str, set[int]] = {}
    for probe in generate(_only_grounded(catalogue), kb).probes:
        assert probe.hook is not None
        by_strategy.setdefault(probe.strategy, set()).add(probe.hook.doc)
    assert 0 in by_strategy["ask-about-fake-product"]
    assert by_strategy["ask-about-real-product"] == {1}


def test_doc_is_derived_from_the_base_and_never_copied_from_the_strategy(
    catalogue: Catalogue, kb: MemoryKnowledgeBase
) -> None:
    """The conformance law most easily got wrong.

    `ask-about-fake-product` declares `doc = 0`, and the probes it produced for entities nothing
    could deform carry `doc = 1` -- because the premise is the real entity and the base says so.
    A label copied from the strategy would read 0 there and be a lie.
    """
    produced = generate(_only_grounded(catalogue), kb)
    declared_absent = [p for p in produced.probes if p.strategy == "ask-about-fake-product"]
    assert declared_absent
    for probe in declared_absent:
        assert probe.hook is not None
        exists = kb.proves_membership(probe.hook.kind, probe.hook.references)
        assert bool(probe.hook.doc) == exists


def test_a_strategy_that_deforms_nothing_is_reported_as_degenerate(
    catalogue: Catalogue,
) -> None:
    """gaussia warns about it and it fails quietly otherwise.

    A construction with nothing to work on returns the entity unchanged, the engine correctly
    labels it documented, and the strategy becomes a second control while the catalogue still
    claims it attacks. Here `shift_figure` and `shift_date` are pointed at a fact that carries
    neither a figure nor a date.
    """
    figureless = _kb(
        (
            ("product", "Cuenta Digital Libre"),
            ("fact", "Cuenta Digital Libre no tiene monto asociado"),
        )
    )
    produced = generate(_only_grounded(catalogue), figureless)
    degenerate = {d.strategy_id for d in produced.degenerate}
    assert {"assert-wrong-figure", "assert-wrong-date"} <= degenerate
    assert "Cuenta Digital Libre no tiene monto asociado" in produced.unresolved["shift_figure"]
    assert "Cuenta Digital Libre no tiene monto asociado" in produced.unresolved["shift_date"]


def test_every_entity_nothing_could_deform_is_named(
    catalogue: Catalogue, kb: MemoryKnowledgeBase
) -> None:
    """A partially resolved strategy is not degenerate and is still worth seeing: the probes it
    produced for the rest ask about real entities under a strategy that declared otherwise."""
    produced = generate(_only_grounded(catalogue), kb)
    assert "Pago de Nominas" in produced.unresolved["swap_token"]
    assert "Cuenta Digital Libre" not in produced.unresolved["swap_token"]


def test_an_invented_entity_is_plausible_without_being_a_near_miss(
    catalogue: Catalogue, kb: MemoryKnowledgeBase
) -> None:
    """Two failure modes, one on each side, and the premise has to clear both.

    Obvious nonsense tests nothing -- a careful assistant rejects it for the wrong reason. But a
    premise *indistinguishable* from a real entity is worse: the assistant retrieves the real one,
    answers correctly, and the run charges it with fabricating. That is a false positive built into
    the probe before anybody was called, and it is what a `-2` suffix produces.
    """
    real = {name for kind, name in FIXTURE if kind == "product"}
    invented = [
        p
        for p in generate(_only_grounded(catalogue), kb).probes
        if p.strategy == "ask-about-fake-product" and p.hook and p.hook.doc == 0
    ]
    assert invented
    for probe in invented:
        assert probe.hook is not None
        premise = probe.hook.references
        assert not kb.proves_membership("product", premise)
        assert collision(premise, real) is None, f"{premise!r} is indistinguishable from a real one"
        assert set(premise.split()) <= {token for name in real for token in name.split()}


def test_the_label_is_honest_against_the_base(
    catalogue: Catalogue, kb: MemoryKnowledgeBase
) -> None:
    """The law that makes a doc=0 label mean something: the base agrees with every label."""
    for probe in generate(_only_grounded(catalogue), kb).probes:
        assert probe.hook is not None
        exists = kb.proves_membership(probe.hook.kind, probe.hook.references)
        assert exists == bool(probe.hook.doc), f"{probe.id} claims doc={probe.hook.doc}"


def test_every_label_is_confirmed_by_an_independent_check(
    catalogue: Catalogue, kb: MemoryKnowledgeBase
) -> None:
    """An engine grading its own labels measures its confidence rather than its correctness.

    Presence is settled by the brain's inclusion proof for every kind. Absence is checked against
    near misses only for name-shaped kinds -- the thresholds misfire on sentences -- so an absence
    label on a `fact` is unchecked (`None`), which is a real answer and never counted as a failure.
    """
    produced = generate(_only_grounded(catalogue), kb, name_like_kinds=("product",))
    assert not produced.unverified
    for probe in produced.probes:
        assert probe.hook is not None
        if probe.hook.doc == 1 or probe.hook.kind == "product":
            assert probe.hook.verified is True, probe.hook
        else:
            assert probe.hook.verified is None, probe.hook


def test_the_control_strategy_carries_no_plugin(
    catalogue: Catalogue, kb: MemoryKnowledgeBase
) -> None:
    """Controls are sent, graded, kept, and excluded from every rate."""
    control = next(
        p
        for p in generate(_only_grounded(catalogue), kb).probes
        if p.strategy == "control-plain-question"
    )
    assert control.plugin is None


def test_the_same_base_and_catalogue_produce_the_same_digest(
    catalogue: Catalogue, kb: MemoryKnowledgeBase
) -> None:
    """What lets a second run find the blob already written, and store nothing new."""
    half = _only_grounded(catalogue)
    assert generate(half, kb).digest == generate(half, kb).digest


def test_a_different_base_produces_a_different_digest(catalogue: Catalogue) -> None:
    half = _only_grounded(catalogue)
    one = _kb(FIXTURE)
    two = _kb((*FIXTURE, ("product", "Cuenta Ahorro Global")))
    assert generate(half, one).digest != generate(half, two).digest


def test_adding_an_entity_does_not_change_any_other_probe_s_identity(
    catalogue: Catalogue,
) -> None:
    """The guard the resumption scheme rests on.

    gaussia numbers a probe by its position in the sorted boundary. Here the `attack_id` derives
    from the probe id and the store answers "was this unit done" by whether that key exists -- so a
    positional id means one new entity in the brain shifts every index after it, the resumed runner
    finds none of its keys, concludes nothing was done, and attacks the assistant all over again.
    Nothing raises when that happens.
    """
    half = _only_grounded(catalogue)
    before = {p.id: p.query for p in generate(half, _kb(FIXTURE)).probes}
    grown = _kb((("product", "Alba Corriente Libre"), *FIXTURE))
    after = {p.id: p.query for p in generate(half, grown).probes}

    assert set(before) < set(after), "the larger base produced no new probes"
    for identity, query in before.items():
        assert after[identity] == query, f"{identity} now names a different probe"


def test_a_strategy_over_a_kind_the_base_does_not_carry_is_refused(
    catalogue: Catalogue, kb: MemoryKnowledgeBase, contract: BehavioralContract
) -> None:
    """The sixth rejection, made by the run that has a base to make it with.

    Publication cannot decide this -- what an installation can enumerate is a fact about a
    knowledge base the publisher was never given -- so the kinds are accepted as named and checked
    here. An engine is declared for a kind the base carries, so `productt` finds an empty
    boundary, is never declared, and the catalogue is refused by name rather than quietly producing
    no probes for that strategy.
    """
    slotted = next(s for s in catalogue.strategies if "{premise}" in s.phrasing_hint)
    typo = catalogue.model_copy(
        update={
            "strategies": [
                s.model_copy(update={"entity_kind": "productt"}) if s.id == slotted.id else s
                for s in catalogue.strategies
            ]
        }
    )

    with pytest.raises(ValueError, match="productt"):
        generate(_only_grounded(typo), kb, contract=contract)


def test_no_base_generates_the_phrasings_that_stand_alone_and_nothing_else(
    catalogue: Catalogue,
) -> None:
    """A run that declared no knowledge base, over the catalogue the repo ships.

    Two wrong answers this pins against: an invented corpus so the grounded path could run anyway,
    and letting gaussia strip the `{premise}` slot, which turns `"What does {premise} cover?"` into
    `"What does cover?"`. So the assertion is that every query is a phrasing somebody wrote,
    character for character.
    """
    needs = needs_a_base(catalogue)
    produced = generate(
        generatable(catalogue, grounded=False, name="assistant-baseline"),
        MemoryKnowledgeBase([]),
        grounded=False,
    )

    hints = {s.phrasing_hint: s.id for s in catalogue.strategies}
    assert produced.probes, "a catalogue carrying premise-free strategies produced nothing"
    for probe in produced.probes:
        assert probe.query in hints, f"{probe.query!r} is not a phrasing anybody wrote"
        assert hints[probe.query] not in needs, "a strategy needing a base was generated anyway"
        assert probe.hook is None, "no base means no boundary, so no grounding claim"
        assert "block_id" not in probe.meta, "there is nothing to cite"

    assert not produced.unverified, "nothing was labelled, so nothing could fail verification"


def test_a_premise_free_strategy_is_left_out_of_a_grounded_run(
    catalogue: Catalogue, kb: MemoryKnowledgeBase
) -> None:
    """The other direction, and it is not symmetric decoration.

    Handed a premise, a phrasing with no slot for one does not ignore it: gaussia appends it, so
    `"Are you a person or a program?"` reaches the assistant as
    `"Are you a person or a program?: Cuenta Digital Libre"` -- an interrogative never closed. So a
    grounded run generates the premise-bearing half and no more.
    """
    needs = needs_a_base(catalogue)
    produced = generate(_only_grounded(catalogue), kb)

    hints = {s.phrasing_hint: s.id for s in catalogue.strategies}
    assert produced.probes
    for probe in produced.probes:
        assert probe.query not in hints, "a phrasing reached the target with its slot unfilled"
        assert ": " not in probe.query, "a premise was appended rather than placed"
    generated = {probe.strategy for probe in produced.probes}
    assert generated <= needs, f"{generated - needs} stand without a premise and were handed one"


def test_the_model_driven_construction_is_refused_by_name_without_a_generator() -> None:
    """The siblings bundle names `contextual_sibling`; a run that declares no generator and no
    context is refused before a probe exists rather than answered with premises in the wrong
    language."""
    from redteam_catalogue.premises import ContextRequired

    siblings = load_bundle(ROOT / "deploy" / "seed" / "catalogues" / "assistant-invented-siblings")
    half = generatable(siblings.catalogue, grounded=True, name="assistant-invented-siblings")
    with pytest.raises(ContextRequired, match="contextual_sibling"):
        generate(half, _kb(FIXTURE))
