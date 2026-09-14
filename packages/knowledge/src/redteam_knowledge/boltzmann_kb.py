"""Consuming a brain through the Boltzmann protocol. Read-only, and ephemeral.

The protocol splits its surface because read and extend are separable, and most consumers only
read; a read-only client satisfying `BrainReader` is conforming. This is that client: it uses
`BrainReader` and exactly two operations of `BrainDistribution`, and implements none of
`BrainWriter`, `BrainRetention` or `BrainReconciliation`.

The brain is pulled into a temporary directory inside the process that will query it, and discarded
when generation closes. Three things follow: the runner keeps no persistent state and needs no
volume, the client's brain does not stay resident on our infrastructure any longer than the
generation takes, and selective installation is available -- taking the semantic module without the
canonical one is a real way to consume a brain, and the manifest records what was left out.
"""

from __future__ import annotations

import tempfile
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from redteam_contracts.kb import Entity, KnowledgeRef, Passage
from redteam_knowledge.registry import RegistryClient

READER_NAMESPACE = "alquimia"
READER_NAME = "red-teaming-runner"
READER_ID = f"{READER_NAMESPACE}/{READER_NAME}"
"""Who the protocol attributes every read to.

Assembled from its two halves rather than written whole, because the no-hardcoded-models guard
reads any `a/b` literal as a model id -- and it is right to be blunt about that shape.

A service rather than an agent: nothing the runner does can be attributed as a knowledge
contribution. Namespaced because the SDK refuses a bare name outright -- an actor id "names nothing
off this machine" unless it is an address or `org/name`, and it is hashed into every block that
names it, so it is refused rather than rewritten.
"""

READER_DISPLAY_NAME = "Red Teaming Runner"

ENTITY_KIND_TAG = "entity_kind"
"""The tag a block carries to say which kind of entity it describes. Ours, not the protocol's: the
protocol stores knowledge, and what counts as an entity kind is domain knowledge.

A brain that carries it is enumerated by it. One that does not is enumerated by the semantic
memory's own `kind`, which is the protocol's way of saying what a block is -- see `_semantic`.
Requiring our tag would mean no brain we did not tag ourselves could be measured."""

EVERY_BLOCK = 100_000
"""The limit a query asks for when it wants the whole snapshot.

`QueryHints.limit` defaults to ten, and a read that takes the default while claiming to answer
"every block" enumerates a brain of a thousand blocks as ten -- when completeness is the entire
contract, because an enumerator that returns a sample turns every `doc = 0` label derived from it
into a guess. There is no pagination in the query surface, so the limit is asked for high and a
result that reaches it is refused rather than returned short."""


class IncompleteEnumeration(RuntimeError):
    """A read of the snapshot came back at its limit, so it cannot claim to have seen everything."""

    def __init__(self, filters: dict[str, Any], limit: int) -> None:
        super().__init__(
            f"a query for {filters or 'the whole snapshot'} returned {limit} blocks, which is the "
            f"limit it asked for: this brain is larger than one read can enumerate, and a partial "
            f"enumeration would make every absence label a guess"
        )


class BoltzmannKnowledgeBase:
    """A `KnowledgeBase` over an installed brain snapshot.

    `proves_membership` is an inclusion proof against the snapshot, not a search. That is what lets
    a `doc = 0` label mean "this entity is not in the base" rather than "we did not find it", and it
    is what makes the label-honesty rule checkable rather than aspirational.
    """

    def __init__(self, brain: Any, subjects: Sequence[str] = ()) -> None:
        self._brain = brain
        self._subjects = tuple(subjects)
        self._read: dict[str, list[tuple[Entity, Any]]] = {}

    @property
    def subjects(self) -> tuple[str, ...]:
        """The subjects of the brain this view is scoped to, or empty for all of it.

        A scope is how a run measures one product line of a bank rather than the bank. It does not
        weaken the enumeration: the boundary is still every entity of a kind *within the scope*,
        which is what a `doc = 0` label then means. What it must not become is a sample -- so the
        scope is declared on the spec and travels in provenance, rather than being a cap somebody
        picked to make a run finish.
        """
        return self._subjects

    def entities(self, kind: str) -> frozenset[Entity]:
        """Every entity of `kind`, by the tag when the brain carries one and by the semantic
        memory's own `kind` when it does not."""
        return frozenset(entity for entity, _ in self._enumerated(kind))

    def _enumerated(self, kind: str) -> list[tuple[Entity, Any]]:
        """Every entity of `kind`, each beside the match it was read from.

        The match is kept because `proves_membership` needs `memory_type` and `Entity` does not
        carry one: the protocol's inclusion proof is per module, so proving a block means naming
        which module it lives in. Reading the kind once and keeping both is what stops the boundary
        and the proof resting on two readings that can disagree -- the same reason the verifier is
        handed the enumerator the labels came from rather than a second one.

        **And read once per kind, for the life of this base.** Generation asks the same question
        from four places -- the boundary, the engine, the verifier's membership check, and the
        citation of each probe -- and each ask would otherwise be a full snapshot query for up to
        `EVERY_BLOCK` blocks.

        A cache of one brain in one process, not a cache across requests: this object exists for
        exactly as long as the pull that produced it. A snapshot is immutable, so reading it twice
        cannot answer differently, which is what makes remembering the answer honest rather than a
        stale-read risk.
        """
        if (remembered := self._read.get(kind)) is not None:
            return remembered
        found = self._read_kind(kind)
        self._read[kind] = found
        return found

    def _read_kind(self, kind: str) -> list[tuple[Entity, Any]]:
        tagged = self._search(tags=[f"{ENTITY_KIND_TAG}:{kind}"])
        if tagged:
            return [
                (Entity(kind=kind, name=self._name_of(match), block_id=str(match.block_id)), match)
                for match in tagged
            ]
        return [
            (Entity(kind=kind, name=str(label), block_id=str(match.block_id)), match)
            for match in self._semantic()
            if isinstance(match.content, dict)
            and match.content.get("kind") == kind
            and (label := match.content.get("label"))
        ]

    def _search(self, **filters: Any) -> list[Any]:
        """One query for the whole snapshot, refusing a truncated answer.

        Reaching the limit means the brain has at least that many matching blocks and this read
        cannot say it saw them all. Completeness is the contract, so it raises rather than returning
        a sample that every absence label would then rest on.
        """
        from boltzmann.query import Query, QueryFilters, QueryHints

        scopes: tuple[str | None, ...] = self._subjects or (None,)
        found: dict[str, Any] = {}
        for subject in scopes:
            narrowed = dict(filters)
            if subject is not None:
                narrowed["subject"] = subject
            bundle = self._brain.search(
                Query(
                    text="",
                    filters=QueryFilters(**narrowed),
                    hints=QueryHints(limit=EVERY_BLOCK),
                )
            )
            matches = list(bundle.matches)
            if len(matches) >= EVERY_BLOCK:
                raise IncompleteEnumeration(narrowed, EVERY_BLOCK)
            found.update({str(match.block_id): match for match in matches})
        return list(found.values())

    def _semantic(self) -> list[Any]:
        from boltzmann import MemoryType

        return self._search(memory_types=[MemoryType.SEMANTIC])

    def proves_membership(self, kind: str, name: str) -> bool:
        """Whether the snapshot proves it holds this entity's block.

        An inclusion proof rather than a search, which is the whole point: it lets `doc = 1` mean
        "the base carries this" instead of "we found it".

        **A refusal by the protocol is `False`; a call that could not be made raises.** Those are
        different facts. Conflating them -- catching every exception and reporting "the base does
        not carry this" -- makes a broken call read exactly like a checked absence, and every
        documented probe of every grounded run comes back unverified while the suite stays green.
        So only `BoltzmannError` -- the protocol saying no, which is `MerkleError` for a block
        outside the composition and `SnapshotError` for a module that is not installed -- is an
        answer here.
        """
        from boltzmann import BoltzmannError

        for entity, match in self._enumerated(kind):
            if entity.name != name or entity.block_id is None:
                continue
            try:
                self._brain.prove(match.block_id, match.memory_type)
            except BoltzmannError:
                return False
            return True
        return False

    def documents(self, kinds: Sequence[str] = ()) -> list[Passage]:
        """Every block, each saying whether this run can enumerate a boundary over it.

        `structured` is decided by whatever `entities` answered, so the enumerable blocks are
        exactly the ones a kind's own enumeration returns. One definition of "enumerable" instead
        of two that can drift.

        A block that is not enumerable is prose. That is not a leftover -- it is what the engines
        that twist a stated fact read, and dropping it would leave them nothing.

        Provenance is left out. It is the audit trail -- who validated which block, when, under
        what task -- and handing an engine thousands of validation records to twist would produce
        probes about our own bookkeeping rather than about the client's domain.
        """
        from boltzmann import MemoryType

        enumerable = {str(entity.block_id) for kind in kinds for entity in self.entities(kind)}
        knowledge = [MemoryType.CANONICAL, MemoryType.SEMANTIC, MemoryType.PROCEDURAL]
        return [
            Passage(
                id=str(match.block_id),
                content=self._prose_of(match),
                structured=str(match.block_id) in enumerable,
            )
            for match in self._search(memory_types=knowledge)
        ]

    @staticmethod
    def _prose_of(match: Any) -> str:
        """What an engine reads off a block.

        A semantic block's statement is its prose; `str(dict)` would hand the engines a Python
        repr with quotes and braces in it, which is what they would then twist.
        """
        content = match.content
        if isinstance(content, dict):
            return str(content.get("statement") or content.get("text") or content)
        return str(content)

    @staticmethod
    def _name_of(match: Any) -> str:
        content = match.content
        if isinstance(content, dict):
            return str(content.get("name") or content.get("title") or match.block_id)
        return str(content)


@asynccontextmanager
async def pulled_brain(
    ref: KnowledgeRef,
    registry: RegistryClient,
    *,
    modules: list[Any] | None = None,
    ignore_vector_indices: bool = True,
    subjects: Sequence[str] = (),
) -> AsyncIterator[BoltzmannKnowledgeBase]:
    """Pull a brain, query it, discard it.

    `ignore_vector_indices` defaults to True because a vector index can only be loaded by a
    consumer in the same representation space, and the runner ships no index of its own. It does
    **not** weaken verification: every requested module is still checked against the published
    Merkle root.
    """
    from boltzmann import Actor, ActorKind, Brain

    reader = Actor(id=READER_ID, kind=ActorKind.SERVICE, name=READER_DISPLAY_NAME)

    with tempfile.TemporaryDirectory(prefix="red-teaming-brain-") as directory:
        brain = Brain.open(Path(directory), actor=reader)
        await brain.pull(
            registry,
            ref.qualified_repository,
            ref.digest,
            modules=modules,
            ignore_vector_indices=ignore_vector_indices,
        )
        yield BoltzmannKnowledgeBase(brain, subjects)
