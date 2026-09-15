"""What probe generation needs from a knowledge base, in its own terms.

Narrower than a brain reader on purpose, and living here rather than in the knowledge package for
one concrete reason: the probe generator depends on this protocol, and the runner depends on the
generator. If the protocol lived with its Boltzmann implementation, every consumer would drag in
`pyboltzmann` for a capability it never uses.

`proves_membership` is the load-bearing one. It is a hash verification -- an inclusion proof against
the snapshot -- not a heuristic, and that is what lets a `doc = 0` label mean "this entity does not
exist in the base" rather than "we did not find it".
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field


class BrainRef(BaseModel):
    """A brain, pinned.

    By digest, never by tag. A tag moves like a git branch, and longitudinal validity needs an
    oracle nobody can move out from under a finished run.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    registry: str = Field(min_length=1)
    repository: str = Field(min_length=1)
    digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")

    @property
    def reference(self) -> str:
        return f"{self.registry}/{self.repository}@{self.digest}"

    @property
    def qualified_repository(self) -> str:
        """The repository with its registry, which is what an OCI client resolves against.

        `repository` alone is not addressable: handed to an OCI client it defaults to Docker Hub,
        which answers a login page rather than a 404, so the failure arrives as "the registry
        answered with text/html" and names the wrong registry.
        """
        return f"{self.registry}/{self.repository}"


class Entity(BaseModel):
    """One thing the base knows about, and where it says so."""

    model_config = ConfigDict(frozen=True)

    kind: str
    name: str
    block_id: str | None = None
    """The block this came from. What makes a probe citable all the way to its source, so a row of
    the result can be checked without anyone taking our word for it."""


class Passage(BaseModel):
    """One unit of the knowledge base, in the shape a probe engine reads it.

    Deliberately not gaussia's `Document`, though it maps onto one: this package depends on
    pydantic and yaml and nothing else, and everything depends on this package. Naming the
    library's type here would put gaussia everywhere for a capability most consumers never use.
    """

    model_config = ConfigDict(frozen=True)

    id: str
    content: str

    structured: bool
    """Whether this passage's knowledge boundary can be enumerated.

    The load-bearing field, and the one that fails quietly when it is wrong. An engine that
    establishes absence declines a passage that says no, because absence from something
    unenumerable is not absence -- so a base whose passages all say `False` produces no probe with a
    boundary behind it.

    Worse, at zero passages the shared engine flow stops asking about boundaries at all and returns
    domain-agnostic probes with **no hook**: a run that meant to test grounding silently measures
    black-box behaviour instead, and nothing about the result says so.
    """

    kind: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


@runtime_checkable
class KnowledgeBase(Protocol):
    """Read-only. The platform never ingests, publishes, reconciles or deletes a brain."""

    def entities(self, kind: str) -> frozenset[Entity]:
        """Every entity of `kind` that exists in the base.

        Completeness is the entire contract: an implementation that returns a sample turns every
        absence label derived from it into a guess.
        """
        ...

    def proves_membership(self, kind: str, name: str) -> bool:
        """Whether this entity is in the base, verified against the snapshot rather than searched
        for."""
        ...

    def documents(self, kinds: Sequence[str] = ()) -> list[Passage]:
        """The passages the probe engines read.

        Args:
            kinds: The entity kinds this run's catalogue names. A passage the base can enumerate
                for one of them comes back `structured=True`; everything else is prose, which is
                what the engines that twist a stated fact read. Passing the kinds rather than
                deriving them is what keeps `structured` a fact about this run's question instead
                of a guess about the corpus.

        Returns:
            Every passage, each declaring whether its boundary is enumerable. Never empty for a
            base that holds anything -- see `Passage.structured` for what an empty list costs.
        """
        ...
