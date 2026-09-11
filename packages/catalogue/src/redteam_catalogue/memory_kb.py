"""An in-memory knowledge base. The tests' brain, and the reference for what the protocol promises.

Membership here is a set lookup rather than an inclusion proof, which is the one thing it cannot
honestly imitate. Everything else -- completeness of enumeration, entities carrying the block
they came
from -- behaves the way the Boltzmann-backed one does.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence

from redteam_contracts.kb import Entity, Passage


class MemoryKnowledgeBase:
    """A brain-shaped fixture."""

    def __init__(self, entities: list[Entity], documents: list[Passage] | None = None):
        self._by_kind: dict[str, set[Entity]] = defaultdict(set)
        for entity in entities:
            self._by_kind[entity.kind].add(entity)
        self._documents = documents or []

    def entities(self, kind: str) -> frozenset[Entity]:
        return frozenset(self._by_kind.get(kind, set()))

    def proves_membership(self, kind: str, name: str) -> bool:
        return any(e.name == name for e in self._by_kind.get(kind, set()))

    def documents(self, kinds: Sequence[str] = ()) -> list[Passage]:
        """What the fixture was handed, unchanged.

        `kinds` is ignored: a fixture states `structured` per passage when it is built, which is
        the point of a fixture -- the cases worth testing are the ones a real base makes awkward to
        produce on purpose, an all-prose corpus among them.
        """
        return list(self._documents)
