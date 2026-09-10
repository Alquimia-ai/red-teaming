"""Reading a brain: what enumeration has to answer, and what it must refuse to answer partially.

Every case here comes from what a real brain looks like: canonical documents, a thousand semantic
blocks, twice as many provenance records, and not one `entity_kind` tag.
"""

from __future__ import annotations

from typing import Any

import pytest

from redteam_knowledge.boltzmann_kb import (
    EVERY_BLOCK,
    BoltzmannKnowledgeBase,
    IncompleteEnumeration,
)


class _Match:
    def __init__(self, block_id: str, content: Any, memory_type: str = "semantic") -> None:
        self.block_id = block_id
        self.content = content
        self.memory_type = memory_type


class _Bundle:
    def __init__(self, matches: list[_Match]) -> None:
        self.matches = matches


class _Brain:
    """A brain that answers a query the way the SDK does: filters narrow, and `hints.limit` caps."""

    def __init__(self, blocks: list[_Match]) -> None:
        self._blocks = blocks
        self.asked: list[Any] = []
        self.proved: list[tuple[str, str]] = []

    def search(self, query: Any) -> _Bundle:
        self.asked.append(query)
        found = self._blocks
        filters = query.filters
        if filters.tags:
            found = [b for b in found if set(filters.tags) <= set(getattr(b, "tags", []))]
        if filters.memory_types:
            wanted = {str(m) for m in filters.memory_types}
            found = [b for b in found if b.memory_type in wanted]
        return _Bundle(found[: query.hints.limit])

    def prove(self, block_id: str, memory_type: str) -> None:
        """The protocol's signature, and it matters that this stub carries it exactly.

        A stub that took the block alone would let the adapter call it that way, swallow the
        `TypeError` as "not a member", and leave every documented probe of every run against a real
        brain unverified while this file stayed green. `test_prove_is_called_with_the_signature_
        the_sdk_declares` is what stops a stub from deciding the contract.

        A block the snapshot does not hold is refused the way the SDK refuses it -- `MerkleError`,
        "the block is not part of this composition" -- rather than by returning something falsey,
        so the adapter's `False` path is exercised through the real exception type.
        """
        from boltzmann.exceptions import MerkleError

        self.proved.append((block_id, memory_type))
        if not any(block.block_id == block_id for block in self._blocks):
            raise MerkleError(f"{block_id} is not part of this composition")
        return None


def _semantic(label: str, kind: str, statement: str = "s") -> _Match:
    return _Match(
        f"sha256:{label}", {"kind": kind, "label": label, "statement": statement}, "semantic"
    )


def test_a_brain_with_no_tags_is_enumerated_by_the_semantic_kind() -> None:
    """A real brain need not carry an `entity_kind` tag at all. Requiring ours would mean no brain
    we did not tag ourselves could ever be measured."""
    brain = _Brain([_semantic("Visa Impulsa", "concept"), _semantic("Cuenta Flash", "concept")])

    found = BoltzmannKnowledgeBase(brain).entities("concept")

    assert {entity.name for entity in found} == {"Visa Impulsa", "Cuenta Flash"}
    assert all(entity.block_id for entity in found), "an entity with no block cannot be cited"


def test_a_kind_the_brain_does_not_carry_enumerates_to_nothing() -> None:
    brain = _Brain([_semantic("Visa Impulsa", "concept")])
    assert BoltzmannKnowledgeBase(brain).entities("policy") == frozenset()


def test_the_tag_still_wins_where_a_brain_carries_it() -> None:
    """Our own convention keeps working: a brain tagged by us is enumerated by the tag, and the
    semantic fallback is only for one that is not."""
    tagged = _Match("sha256:tagged", {"name": "Meridian Salud"}, "canonical")
    tagged.tags = ["entity_kind:policy"]  # type: ignore[attr-defined]
    brain = _Brain([tagged, _semantic("Meridian Salud", "policy")])

    found = BoltzmannKnowledgeBase(brain).entities("policy")

    assert {entity.block_id for entity in found} == {"sha256:tagged"}


def test_a_read_that_reaches_its_limit_is_refused_rather_than_returned_short() -> None:
    """`QueryHints.limit` defaults to ten; a read that takes it enumerates a brain of a thousand
    blocks as ten. Completeness is `enumerate_entities`' entire contract: a sample turns every
    `doc = 0` label into a guess, so a truncated read has to raise."""
    brain = _Brain([_semantic(f"e{i}", "concept") for i in range(EVERY_BLOCK)])

    with pytest.raises(IncompleteEnumeration, match="larger than one read"):
        BoltzmannKnowledgeBase(brain).entities("concept")


def test_every_block_is_read_not_the_first_page() -> None:
    brain = _Brain([_semantic(f"e{i}", "concept") for i in range(500)])
    assert len(BoltzmannKnowledgeBase(brain).entities("concept")) == 500


def test_the_audit_trail_is_not_handed_to_the_engines_as_prose() -> None:
    """A real brain carries about twice as many validation records as blocks of knowledge.
    Twisting those produces probes about our own bookkeeping."""
    brain = _Brain(
        [
            _semantic("Visa Impulsa", "concept", statement="La tarjeta Visa Impulsa ..."),
            _Match("sha256:doc", "**URL:** https://popular ...", "canonical"),
            _Match("sha256:audit", {"record": {"verdict": "validated"}}, "provenance"),
        ]
    )

    passages = BoltzmannKnowledgeBase(brain).documents(("concept",))

    assert {p.id for p in passages} == {"sha256:Visa Impulsa", "sha256:doc"}
    assert [p.structured for p in passages].count(True) == 1


def test_a_semantic_blocks_prose_is_its_statement_not_its_repr() -> None:
    """`str(dict)` hands an engine a Python repr with braces and quotes in it, which is then what
    it twists."""
    brain = _Brain([_semantic("Visa Impulsa", "concept", statement="La tarjeta cubre X.")])

    [passage] = BoltzmannKnowledgeBase(brain).documents(())

    assert passage.content == "La tarjeta cubre X."


def test_membership_is_proved_against_the_block_the_entity_came_from() -> None:
    brain = _Brain([_semantic("Visa Impulsa", "concept")])
    kb = BoltzmannKnowledgeBase(brain)

    assert kb.proves_membership("concept", "Visa Impulsa")
    assert not kb.proves_membership("concept", "Visa Que No Existe")

    assert brain.proved == [("sha256:Visa Impulsa", "semantic")], (
        "the proof names the block and the module it lives in, both read off the match the entity "
        "was enumerated from"
    )


def test_prove_is_called_with_the_signature_the_sdk_declares() -> None:
    """The guard this class of bug needs.

    Every other test here reaches `prove` through a stub, and a stub is free to accept whatever it
    is handed -- which is how a call with one argument against a two-argument signature could
    survive indefinitely, silently answering "not a member" for every entity. So the call is
    held against the real declaration instead of against a double: `BrainReader` is the contract
    this package consumes, and its `prove` is what the adapter has to satisfy.
    """
    import inspect

    from boltzmann.protocol.operations import BrainReader

    declared = list(inspect.signature(BrainReader.prove).parameters)

    assert declared == ["self", "block_id", "memory_type"], (
        f"the SDK's `prove` now takes {declared}; `proves_membership` passes block_id and "
        f"memory_type and has to be brought back in line"
    )


def test_a_proof_that_could_not_be_made_is_not_reported_as_a_missing_block() -> None:
    """A refusal by the protocol is an answer; a broken call is not.

    This is the distinction that keeps a signature bug visible: an adapter that caught everything
    and reported it as "the base does not carry this" would make a `doc = 1` label that was never
    checked read exactly like one that was checked and failed. Only `BoltzmannError` is an answer.
    """

    class _Broken(_Brain):
        def prove(self, block_id: str, memory_type: str) -> None:
            raise TypeError("prove() takes 2 positional arguments but 3 were given")

    kb = BoltzmannKnowledgeBase(_Broken([_semantic("Visa Impulsa", "concept")]))

    with pytest.raises(TypeError):
        kb.proves_membership("concept", "Visa Impulsa")


def test_the_reader_identity_is_one_the_protocol_accepts() -> None:
    """`Brain.open` refuses a bare name outright -- an actor id "names nothing off this machine"
    unless it is an address or `org/name`, and it is hashed into every block that names it, so the
    SDK refuses rather than rewrites. A bare reader name would make every brain pull raise.
    """
    from boltzmann.identity.principal import parse_actor_id

    from redteam_knowledge.boltzmann_kb import READER_ID

    parse_actor_id(READER_ID, field="actor id")


def test_a_brain_reference_carries_the_registry_it_lives_in() -> None:
    """`repository` alone is not addressable: handed to ORAS it defaults to Docker Hub, which
    answers a login page rather than a 404 -- so the failure would read "the registry answered with
    text/html" and name the wrong registry."""
    from redteam_contracts.kb import KnowledgeRef

    ref = KnowledgeRef(
        registry="ghcr.io", repository="alquimia-ai/assistant-brain", digest="sha256:" + "a" * 64
    )

    assert ref.qualified_repository == "ghcr.io/alquimia-ai/assistant-brain"
    assert ref.qualified_repository in ref.reference


def test_a_kind_is_read_from_the_brain_once_however_often_it_is_asked_for() -> None:
    """Generation asks the same question from four places, and each ask would be a full snapshot
    query.

    The boundary, the engine, the verifier's membership check and each probe's citation all go
    through `entities`, so a run would pay `(2 to 4) x probe_count` reads of the whole brain --
    each one asking for up to `EVERY_BLOCK` blocks. A snapshot is immutable, so reading it twice
    cannot answer differently; remembering the answer for the life of this base is honest, and the
    base lives exactly as long as the pull that produced it.
    """
    brain = _Brain([_semantic("Visa Impulsa", "concept"), _semantic("Cuenta Flash", "concept")])
    kb = BoltzmannKnowledgeBase(brain)

    first = kb.entities("concept")
    asked = len(brain.asked)
    for _ in range(5):
        assert kb.entities("concept") == first

    assert len(brain.asked) == asked, "the snapshot was read again for an answer it already had"
    assert first, "the fixture produced nothing, so the test proves nothing"


def test_two_kinds_are_two_answers_and_neither_stands_in_for_the_other() -> None:
    brain = _Brain([_semantic("Visa Impulsa", "concept"), _semantic("Plan Oro", "product")])
    kb = BoltzmannKnowledgeBase(brain)

    assert {e.name for e in kb.entities("concept")} == {"Visa Impulsa"}
    assert {e.name for e in kb.entities("product")} == {"Plan Oro"}
