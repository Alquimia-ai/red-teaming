"""The `EntityEnumerator` over a Boltzmann brain.

Gaussia ships none and explains why: "enumerating 'every article that exists' cannot be derived
from a corpus by a general library", so the interface is specified and the implementation is
irreducibly domain knowledge. This is that implementation, and it is the seam where the Boltzmann
protocol meets Roast Me.

Completeness is the entire contract. An enumerator that returns a sample turns every absence label
derived from it into a guess -- and a `doc = 0` label is the strongest claim this method makes.

There is a second reason to enumerate a brain rather than extract mentions from text, and it comes
from gaussia's own documentation: the mention extractor "reads compound identifiers, and a corpus of
ordinary words defeats it". Over prose product pages it returns mentions that are not entities --
phone numbers, PDF filenames, footer anchors -- and nothing fails: each becomes a probe. Enumerating
by verifiable membership avoids that whole class of false positive, and the knowledge bases this
platform reads are prose in the client's language.
"""

from __future__ import annotations

from gaussia.core.entity_enumerator import EntityEnumerator
from gaussia.schemas.roastme import Document

from redteam_contracts.kb import KnowledgeBase


class BrainEntityEnumerator(EntityEnumerator):  # type: ignore[misc]  # gaussia ships no stubs
    """Lists entities from a knowledge base, completely."""

    def __init__(self, kb: KnowledgeBase) -> None:
        self._kb = kb

    def enumerate_entities(self, kind: str, documents: list[Document]) -> frozenset[str]:
        """Every entity of `kind` in the base.

        `documents` is ignored on purpose. The base is the authority on what exists, not the
        subset of it that happens to have been passed in -- and answering from the subset is
        exactly how a complete enumeration quietly becomes a sample.
        """
        return frozenset(entity.name for entity in self._kb.entities(kind))

    def block_for(self, kind: str, name: str) -> str | None:
        """Where the base says this entity exists.

        Not part of gaussia's interface, and the reason a probe is citable all the way to its
        source: a row of the result can be checked against the block it came from.
        """
        for entity in self._kb.entities(kind):
            if entity.name == name:
                return str(entity.block_id) if entity.block_id else None
        return None
