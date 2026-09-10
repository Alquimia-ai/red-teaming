"""The run spec: frozen at acceptance, and the only account of what was asked for.

Once written, what ran is what this file says -- not what anyone remembers requesting. Everything a
run needs is here, and everything here is either a reference or a number: no credentials, no model
objects, no code paths. Credentials travel as a reference to a secret, and models as ids, because
both are provenance and both have to be declarable.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from redteam_contracts.kb import KnowledgeRef
from redteam_contracts.serving import ServingPath

DEFAULT_MAX_RETRIES = 3
"""Enough to ride out a burst of rate limiting; few enough that a target that is down is given up on
within one probe's worth of attempts rather than hammered."""


class ConnectorSpec(BaseModel):
    """How to reach the assistant under test, and what it is allowed to do while being attacked."""

    model_config = ConfigDict(frozen=True)

    kind: str
    """Which target adapter reaches the assistant: `alquimia` for a live runtime, `replay` for
    recorded answers. The target package refuses anything else by name."""

    endpoint: str
    secret_ref: str
    """A reference the secret resolver looks up. Never the credential itself."""

    declared_capabilities: tuple[str, ...] = ()
    """What the assistant can do. If it can act -- move money, book, send messages -- the attack
    fires real side effects, and the search sends far more exchanges than the profiler does."""

    safe_mode: bool = True
    """Attacking a target with the capacity to act requires a sandbox agreement. This is the gate
    that enforces it before the first turn, not a configuration checkbox."""

    options: dict[str, Any] = Field(default_factory=dict)
    """What a particular kind of adapter needs beyond an endpoint and a credential -- the assistant
    id and agentspace a runtime addresses, for instance. Kind-specific by design: a field per
    adapter on this spec would grow with every transport, and most of them would be null for any
    given run."""

    min_interval_seconds: float = Field(default=0.0, ge=0.0)
    """How much load the target's infrastructure takes: the least time between two calls. Zero is
    no pacing, which is right for a mock and wrong for somebody else's production assistant. It
    lives on the spec because it is a fact about the engagement, not about the platform."""

    max_retries: int = Field(default=DEFAULT_MAX_RETRIES, ge=0)
    """How many times one probe may be sent again after a failure the policy says will recover --
    a rate limit, a gateway that was down, a timeout. Every retry is a real call, charged to the
    budget and paced by the rate gate. Zero is one attempt and no second chance. Transport-generic,
    so a field rather than an `options` knob."""

    @property
    def can_act(self) -> bool:
        """Whether this target can produce real side effects when attacked.

        Whether that is *allowed* is checked at the API's entry gate, not here: a model validator
        that refuses would make the spec unrepresentable, and a rejected run still has to be written
        down as what was asked for.
        """
        return bool(self.declared_capabilities)


class ModelSpec(BaseModel):
    """A model the run declared, and everything needed to build one.

    Named for the role rather than for the judge, because a run declares more than one instrument:
    the judge that grades, the generator that writes premises and the attackers that steer
    conversations are different, and a probe set written by one model is not the set another would
    have written.

    Every field here ends up in provenance, and `provider` earns that place as much as `model`
    does: **where** a model was served is part of what it measured, because one serving path
    exposes logprobs and another does not.
    """

    model_config = ConfigDict(frozen=True)

    model: str
    provider: str | None = None
    """Which registered builder constructs this model.

    Absent is legal and means this run cannot build one, which fails loudly at wiring time rather
    than defaulting to somebody's favourite. A fixture run that grades with a deterministic
    stand-in never needs it.
    """

    endpoint: str | None = None
    """Where an OpenAI-compatible server answers, for a self-hosted model. Absent for a hosted
    provider that knows its own address."""

    secret_ref: str | None = None
    self_hosted: bool = False

    requests_per_second: float | None = Field(default=None, gt=0)
    """Pacing for this model's provider, carried by the model itself.

    One 429 on the first call can make a grader settle its estimator on "this provider has no
    usable logprobs" and remember the denial, so every later grade raises without calling. Retries
    do not cover that; pacing does, and the model is what carries it.
    """

    reasoning_budget: int | None = Field(default=None, ge=1)
    """How many tokens a reasoning model may spend before its verdict. Absent takes the measured
    default. A model that reasons longer truncates before the verdict token, which reads as a
    provider with no logprobs rather than as what it is -- so a judge that needs more says so
    here."""

    @property
    def serving_path(self) -> ServingPath:
        """Where this model runs, as the provenance records it."""
        return ServingPath.SELF_HOSTED if self.self_hosted else ServingPath.HOSTED_API

    def declares_provider(self) -> bool:
        """Whether this run can build the model: `provider` names a builder.

        The one reading of the field, shared by the gate and by the builder itself. `None` and
        `""` both declare none; three sites reading the field three ways is how an empty string
        gets through a gate and fails after the attack.
        """
        return bool(self.provider)


class ProbeContext(BaseModel):
    """What this assistant's world sounds like, declared rather than inferred.

    A premise has to read as something a real user of *this* assistant would send. That is not
    derivable from a corpus and it is not ours to guess: a false premise phrased in the wrong
    language, or in the wrong register, measures the assistant's tolerance for odd input instead of
    its grounding. gaussia says the same thing from its side -- its prompts are English and a model
    answers in the language it is addressed in, so a Spanish corpus with no language given produces
    English questions asked about Spanish product names.

    Declared here rather than carried by the catalogue because one catalogue serves several
    engagements: the risk families are the same for two banks, and the language and register are
    not. It is frozen with the spec and travels in provenance, because a probe set written under
    one context is not the set another would have produced.
    """

    model_config = ConfigDict(frozen=True)

    language: str
    """The language premises and questions are written in. A BCP-47 tag, `es-419` or `en`."""

    domain: str
    """What the assistant is, in one phrase. Reaches the model that writes premises, so it reads as
    an instruction rather than as a label: "Dominican retail banking" works."""

    tone: str | None = None
    """How this client's real traffic sounds, when it is worth saying. The difference between a
    premise a customer would type and one an evaluator would write."""


class ExploitSpec(BaseModel):
    """The search's own parameters -- control, and they steer the run without leaving it.

    `tau` and `eta` are the user's judgement about their own domain: how reproducibly a category
    must break the assistant to be reported, and how weak a profiled weakness must be to seed a
    category. They are thresholds of the search, and they reach the manifest only as a record of
    what the search was configured with.

    `kappa` and `delta` are absent on purpose. Each is compared against a number a substitutable
    component produces, so its scale travels with that implementation; gaussia resolves both from
    the configured components and refuses to run with a stranger's number.
    """

    model_config = ConfigDict(frozen=True)

    tau: float = Field(ge=0.0, le=1.0)
    """The reproducible-failure score a category must reach to count."""

    eta: float = Field(ge=0.0, le=1.0)
    """The weakness rate at which a profiled weakness seeds a category."""

    lambda_: float = Field(default=1.0, ge=0.0)
    """How much a category's variance across samples is held against it."""

    queries_per_category: int = Field(default=10, ge=2)
    pool_size: int = Field(default=20, ge=1)
    max_attributes: int = Field(default=3, ge=1)
    """The longest conjunction the search will refine. Refinement is exhaustive over
    sub-conjunctions, so this bounds the cost of a run."""


class Budget(BaseModel):
    """Where a run stops. The search decides how many target calls it wants; this decides how many
    it gets."""

    model_config = ConfigDict(frozen=True)

    max_tokens: int | None = Field(default=None, gt=0)
    """Declared but refused at the gate: there is no honest token ledger to enforce it against."""

    max_wall_seconds: int | None = Field(default=None, gt=0)
    max_target_calls: int | None = Field(default=None, gt=0)


class RunSpec(BaseModel):
    """What a consumer asked for, frozen."""

    model_config = ConfigDict(frozen=True)

    run_id: str
    kb_ref: KnowledgeRef | None = None
    """Absent for a run that generates only the strategies which stand without a knowledge base."""

    kb_subjects: tuple[str, ...] = ()
    """Which subjects of the brain are in scope. Empty is the whole brain.

    A scope is how a run measures one product line rather than a whole bank, and it does not weaken
    the enumeration: the boundary is still every entity of a kind *within the scope*, which is what
    a `doc = 0` label then means. Declared here rather than chosen at generation so it is frozen
    with the run and readable afterwards -- a boundary somebody narrowed to make a run finish, with
    nothing saying so, is a sample presented as a census."""

    catalogues: tuple[str, ...]
    """The catalogue bundles the run generates from, by published name. The version each name
    resolved to at acceptance is frozen in `catalogue_versions`, and the contract every bundle
    carries is frozen with it."""

    catalogue_versions: dict[str, int] = Field(default_factory=dict)
    """Per catalogue name, the published version this run generates from. Empty means "resolve me":
    the API resolves each name to its newest version at acceptance and freezes it here, and
    generation reads exactly that. Once set, a catalogue published afterwards cannot change this
    run's probe set -- which matters because a probe's identity is content-derived, so a different
    set means different keys, and a resumed runner would find none of its traces and attack the
    assistant all over again."""

    plugins: tuple[str, ...]
    strategies: tuple[str, ...]
    connector: ConnectorSpec
    judge: ModelSpec
    """The control judge: grades every exchange inside the run to steer it. Needs usable
    logprobs."""

    context: ProbeContext | None = None
    """How premises should read for this engagement. Absent only for a run whose catalogue names
    nothing that needs it -- which means the deterministic constructions alone."""

    embedder: ModelSpec | None = None
    """The embedding model the realism estimator measures categories with. Declared like every other
    model, because which embedder scored realism is part of what the search measured."""

    realism_prior: str | None = None
    """The natural-query prior the run measures realism against, by published name. The client's
    own traffic, published to the store; an invented pool measures our imagination."""

    exploit: ExploitSpec | None = None
    """The search's parameters. **The exploitation stage runs only when this, `generator`,
    `embedder` and `realism_prior` are all declared** -- it needs a model to write queries, one to
    embed them, a pool to compare against and thresholds to search with. Absent any one, the run
    profiles and records that it did not exploit, rather than exploiting with something it was not
    given."""

    generator: ModelSpec | None = None
    """The model that writes premises, for the strategies whose construction needs one.

    Declared apart from the judge rather than reused from it, even when both name the same id: they
    are two instruments and they fail differently, and a probe set carries the generator on
    `Probe.model` so one model's set is never mistaken for another's. Absent for a run whose
    catalogue names only deterministic constructions.
    """

    attackers: dict[str, ModelSpec] = Field(default_factory=dict)
    """Per attacker id a catalogue's delivery sidecar may name, the model that plays it.

    A catalogue declares that a strategy is delivered as a conversation and names who steers it by
    id; it never names a model, because a versioned asset naming one freezes the choice forever
    while the model has to stay the run's decision, with its own credential and its own line in
    the provenance. The id is the requirement; this is where the run meets it. An id nothing the
    run generates names is inert, and an id something names and this does not bind is refused at
    the gate, by name.
    """

    replicas: int = Field(ge=1)
    """N, frozen here. A run ends when the plan minus the store is empty -- a property of the store
    rather than a statistical criterion."""

    budget: Budget = Budget()
    webhook_url: str | None = None
