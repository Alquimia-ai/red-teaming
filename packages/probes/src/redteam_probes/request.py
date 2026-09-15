"""What generation is asked for, and what it reports.

Both shapes are the runner's: the request is read off the frozen spec, and the report is what
`probes.json` records so a resumed attempt -- or anyone reading the store -- knows exactly which
catalogue versions, which contract and which constructions produced the plan.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from redteam_contracts.kb import BrainRef
from redteam_contracts.run_spec import ModelSpec, ProbeContext, RunSpec


class GenerationRequest(BaseModel):
    """Everything generation needs from a run, and nothing about how the run is conducted."""

    model_config = ConfigDict(frozen=True)

    run_id: str
    brain: BrainRef | None = None
    brain_subjects: tuple[str, ...] = ()
    """Which subjects of the brain the run declared in scope. Empty is the whole brain."""

    catalogues: tuple[str, ...]
    catalogue_versions: dict[str, int] = Field(default_factory=dict)
    """Per catalogue name, the published version the run froze at acceptance. A name absent here
    resolves to the newest version -- the rehearsal path, for a spec nobody accepted -- and the
    version that was actually used is recorded in the run's `probes.json` either way."""

    plugins: tuple[str, ...] = ()
    strategies: tuple[str, ...] = ()

    context: ProbeContext | None = None
    """Language, domain and tone. Reaches the constructions that need a model, and a key naming one
    without it is refused before a probe exists."""

    generator: ModelSpec | None = None
    """The model that writes premises for the constructions that need one. Its credential travels
    by reference like every other; the runner resolves it and hands the built model in."""

    @classmethod
    def from_spec(cls, spec: RunSpec) -> GenerationRequest:
        return cls(
            run_id=spec.run_id,
            brain=spec.brain,
            brain_subjects=spec.brain_subjects,
            catalogues=spec.catalogues,
            catalogue_versions=dict(spec.catalogue_versions),
            plugins=spec.plugins,
            strategies=spec.strategies,
            context=spec.context,
            generator=spec.generator,
        )


class GenerationReport(BaseModel):
    """What generation produced, and what it could not do.

    A probe set is not just its probes: what could not be built is a fact about the run, and each
    field here answers a question a consumer would otherwise have to guess at.
    """

    model_config = ConfigDict(frozen=True)

    probes_digest: str
    probe_count: int
    skipped_existing: bool = False
    """True when nothing was written. For a run whose generation already closed -- its `probes.json`
    is read back and nothing is generated -- and for a second run over the same base and catalogue,
    which generates, finds the blob already there, and skips the write: the set is shared, the
    generation is not."""

    catalogue_versions: dict[str, int] = Field(default_factory=dict)
    """The version of each catalogue the set was generated from. What the run's `probes.json`
    records, so a resumed run can say exactly which catalogue produced its plan."""

    contract_digest: str = ""
    """The digest of the contract every selected catalogue carries, which validated this set and
    will grade the run. Recorded because "the newest at the time" is not something a later reader
    can reconstruct."""

    degenerate_strategies: tuple[str, ...] = ()
    """Strategies that produced only documented premises and so tested nothing they claimed to."""

    engines_ran: tuple[str, ...] = ()
    """Which engines composed this set. An engine that ran and produced nothing is invisible in the
    probes themselves, which is exactly the case worth being able to see."""

    unresolved_entities: dict[str, list[str]] = Field(default_factory=dict)
    """Per construction, the entities it could not deform into a defensible premise. Each one still
    became a probe -- one asking about something real under a strategy that declared otherwise."""

    unverified_probes: tuple[str, ...] = ()
    """Probes whose `doc` label the verifier could not confirm. Kept rather than dropped: silently
    shrinking a probe set reports a smaller denominator as though the whole thing was measured."""

    grounded: bool = True
    """Whether this set was generated against a knowledge base.

    `False` is a black-box run: every probe is hookless, carries no `doc` label and cites no block,
    so nothing downstream may read it as evidence about grounding. Reported rather than inferred
    because the two sets are otherwise indistinguishable."""

    strategies_set_aside: tuple[str, ...] = ()
    """Strategies of the named catalogues this run's shape could not generate from.

    For a run with no base, the ones that lean on `{premise}`; for a run with one, the ones that
    stand without a premise and would otherwise have had it appended. Reported for the reason the
    constructions report what they could not build: a silence would read as nothing missing."""

    brain_digest: str | None = None
    """The pinned brain actually read.

    None when a brain was supplied but no selected strategy used it.
    """

    language: str | None = None
    generator_model: str | None = None
