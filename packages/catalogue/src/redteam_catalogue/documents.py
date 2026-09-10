"""Passages as gaussia reads them, and the check that a base can answer what it was asked.

The single translation between the contracts' `Passage` and gaussia's `Document`. It lives here
rather than in the contracts package because that package depends on pydantic and yaml and nothing
else, and everything depends on it -- naming gaussia's type there would put the library into every
image, including the one that never uses it.

**The check is the part worth reading.** With no documents at all, the shared engine flow does not
fail: it returns domain-agnostic probes with an empty hook, on purpose, so a black-box run works
through the same interface. That is right for a run that asked for no knowledge base and wrong for
a run that supplied one -- the second gets a probe set that tests grounding against nothing, and
every downstream number is computed over it without complaint. A run that named a brain and got
back a corpus it cannot ground on has a broken pull or a mistagged brain, and it should say so
before spending a single call.
"""

from __future__ import annotations

from collections.abc import Sequence

from gaussia.schemas.roastme import Document

from redteam_contracts.kb import Passage


class UngroundableCorpus(ValueError):
    """A run supplied a knowledge base and the base cannot support the probes it asked for.

    Raised rather than degraded. The degraded path is silent by construction -- hookless probes are
    a legitimate artifact for a black-box run -- so nothing further down can tell the two apart.
    """


def to_documents(passages: Sequence[Passage]) -> list[Document]:
    """The same passages, in the shape every probe engine reads."""
    return [
        Document(
            id=passage.id,
            content=passage.content,
            structured=passage.structured,
            kind=passage.kind,
            metadata=dict(passage.metadata),
        )
        for passage in passages
    ]


def require_groundable(
    passages: Sequence[Passage], *, needs_boundary: bool, declared: bool = True
) -> None:
    """Refuse a corpus that cannot answer the question this run is asking.

    Args:
        passages: What the base returned.
        needs_boundary: Whether any configured engine establishes absence. When it does, a corpus
            with no enumerable passage cannot produce a single `doc = 0` label anybody can defend,
            which is the claim the whole method rests on.
        declared: Whether the run named a knowledge base at all. This is the distinction the module
            docstring above draws and the signature could not express: an empty corpus is a broken
            pull for a run that supplied a base, and simply the state of the world for a run that
            supplied none. Both were refused, so the second could never run -- which is why the
            fixture existed.

    Raises:
        UngroundableCorpus: A declared base came back empty, or holds nothing enumerable for a run
            that needs a boundary.
    """
    if not declared:
        return
    if not passages:
        raise UngroundableCorpus(
            "the knowledge base returned no passages. Generation would still produce probes -- "
            "domain-agnostic ones, carrying no hook -- so the run would measure black-box "
            "behaviour while reporting itself as knowledge-grounded. Check the pull before "
            "spending the run."
        )
    if needs_boundary and not any(passage.structured for passage in passages):
        raise UngroundableCorpus(
            f"none of the {len(passages)} passages is enumerable, and an engine that decides "
            f"absence is configured. Every `doc = 0` label it produced would rest on a boundary "
            f"nobody could read. Tag the blocks that carry entities, or drop the engine."
        )
