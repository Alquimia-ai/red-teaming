"""The routes. Each one validates, reads or writes, and none of them does the work.

POST /runs                 validate, freeze `spec.json`, launch a runner, answer 202
POST /runs:validate        the same gate, nothing written, nothing launched
GET  /runs/{id}            phase from the store, liveness from the platform
GET  /runs/{id}/result     the manifest, once the run closed
POST /runs/{id}:resume     launch a runner again; it resumes from the difference
POST /catalogues           validate and publish a bundle as one version
POST /catalogues:validate  the same checks, nothing written
GET  /catalogues           every published name and its versions
POST /priors, GET /priors  the natural-query pools a run measures realism against
GET  /probes/{digest}      one probe set, by content
"""

from __future__ import annotations

import json
from http import HTTPStatus
from typing import Any

from fastapi import FastAPI, HTTPException, Response
from pydantic import BaseModel, Field, ValidationError

from redteam_api.validation import ValidationFailure, resolve_versions, validate
from redteam_contracts.manifest import RunPhase
from redteam_contracts.run_spec import RunSpec
from redteam_dispatch import JobState


def _version() -> str:
    """The installed distribution's version, which release-please bumps; a placeholder when this
    module is imported from a checkout nothing installed."""
    from importlib.metadata import PackageNotFoundError, version

    try:
        return version("red-teaming-api")
    except PackageNotFoundError:
        return "0.0.0"


app = FastAPI(
    title="Red Teaming API",
    version=_version(),
    summary="Accepts runs, freezes the spec, launches a runner, publishes catalogue bundles and "
    "priors, and answers state from the store and the platform.",
)


class AcceptedRun(BaseModel):
    run_id: str
    result_location: str
    """Where the manifest will appear. The consumer knows where to look before there is anything to
    look at."""

    catalogue_versions: dict[str, int]
    """What the gate froze: the version each catalogue name resolved to at acceptance."""

    launched: bool
    """Whether this request launched a runner. False when the platform refused a second one because
    the first is still running, which is the run exactly as accepted as the answer says."""


class ValidatedRun(BaseModel):
    """What `POST /runs` would freeze, without freezing it."""

    run_id: str
    catalogue_versions: dict[str, int]
    contract_digest: str
    secret_refs: list[str]
    """Every reference the runner would resolve, so an operator can check the deployment holds
    them."""


class RunStatusResponse(BaseModel):
    run_id: str
    phase: RunPhase
    runner: JobState
    stalled: bool
    planned: int | None
    closed: int
    failed: int
    pending: int | None


class Relaunched(BaseModel):
    run_id: str
    launched: bool
    runner: JobState


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


# ---- runs ---------------------------------------------------------------------------------------


def _gate(spec: RunSpec) -> tuple[RunSpec, str]:
    """Every check, and the spec as it would be frozen: the versions pinned, nothing else touched.

    Raises the HTTP error the failure deserves: 400 for a request the consumer has to change, 422
    for catalogues that disagree on the contract, 503 for a deployment whose store is not what
    publishing left it.
    """
    from redteam_api import deps
    from redteam_catalogue.assets import EmptySelection, NothingToGenerate
    from redteam_secrets.resolver import SecretNotFound
    from redteam_store.contract import ContractMismatch, ContractMissing

    published = deps.catalogue_versions()
    try:
        versions = resolve_versions(spec, published)
        validate(spec, known_catalogues=frozenset(published))
        _, contract_digest = deps.shared_contract(versions)
        selection = deps.effective_selection(spec, versions)
        validate(
            spec,
            known_catalogues=frozenset(published),
            attackers_named=deps.attackers_named(spec, versions),
            model_driven=selection.model_driven,
        )
        pinned = spec.model_copy(update={"catalogue_versions": versions})
        if deps.hands_values():
            for ref in deps.secret_refs_for(pinned):
                deps.resolver().resolve(ref)
    except ContractMismatch as disagree:
        raise HTTPException(status_code=422, detail=str(disagree)) from disagree
    except ContractMissing as unseeded:
        raise HTTPException(status_code=503, detail=str(unseeded)) from unseeded
    except SecretNotFound as missing:
        raise HTTPException(
            status_code=400,
            detail=f"secret reference {missing.ref!r} resolves to nothing in this deployment; "
            f"the runner would die at launch looking for it",
        ) from missing
    except (ValidationFailure, EmptySelection, NothingToGenerate, ValueError) as refused:
        raise HTTPException(status_code=400, detail=str(refused)) from refused
    return pinned, contract_digest


@app.post("/runs:validate", response_model=ValidatedRun)
def validate_run(spec: RunSpec) -> ValidatedRun:
    """The gate alone: what `POST /runs` would freeze and launch, with nothing written."""
    from redteam_api import deps

    pinned, contract_digest = _gate(spec)
    return ValidatedRun(
        run_id=pinned.run_id,
        catalogue_versions=pinned.catalogue_versions,
        contract_digest=contract_digest,
        secret_refs=list(deps.secret_refs_for(pinned)),
    )


@app.post("/runs", status_code=202, response_model=AcceptedRun)
def create_run(spec: RunSpec) -> AcceptedRun:
    """Validate, freeze, launch, answer. In that order, and none of them is doing the work.

    Returns 202 because the run has been accepted, not performed. The API does not wait, does not
    follow progress, and keeps nothing in memory.

    A run id that is already frozen is a retry, and a retry is checked: the consumer's request has
    to equal what the frozen spec holds, whole, or the answer is 409 -- the id names a run that was
    asked for differently, and a change needs a new id. The one leniency is for what the gate itself
    resolves -- the pinned catalogue versions -- which a consumer sends unresolved and the frozen
    spec holds resolved.
    """
    from redteam_api import deps
    from redteam_store import layout
    from redteam_store.interface import ObjectAlreadyExists

    asked = spec
    pinned, _ = _gate(spec)
    try:
        deps.store().put(
            layout.spec(pinned.run_id),
            pinned.model_dump_json(indent=2).encode(),
            content_type="application/json",
        )
    except ObjectAlreadyExists:
        frozen = RunSpec.model_validate_json(deps.store().get(layout.spec(pinned.run_id)))
        differing = _fields_that_differ(asked, frozen)
        if differing:
            raise HTTPException(
                status_code=409,
                detail=f"run {pinned.run_id!r} is already frozen with a different spec; the retry "
                f"differs in {differing}. A retry has to repeat the request; a change needs a "
                f"new run id.",
            ) from None
        pinned = frozen

    launched = _launch(pinned)
    return AcceptedRun(
        run_id=pinned.run_id,
        result_location=layout.manifest(pinned.run_id),
        catalogue_versions=dict(pinned.catalogue_versions),
        launched=launched,
    )


def _launch(spec: RunSpec) -> bool:
    """Ask the platform for one runner. False when it refused a second one for a run whose first is
    still running -- the uniqueness invariant working, not an error."""
    from redteam_api import deps
    from redteam_dispatch import AlreadyRunning, DispatchError

    try:
        deps.dispatcher().launch(spec.run_id, secret_refs=deps.secret_refs_for(spec))
    except AlreadyRunning:
        return False
    except DispatchError as refused:
        raise HTTPException(
            status_code=503, detail=f"the platform refused to launch a runner: {refused}"
        ) from refused
    return True


def _fields_that_differ(asked: RunSpec, frozen: RunSpec) -> list[str]:
    """The fields of the consumer's request whose value the frozen spec does not hold.

    Compared as values, whole, nested models included, because a partial comparison over what the
    consumer set misses a removal -- a retry that emptied `connector.options` or dropped a judge's
    `secret_ref` would read as identical and the runner would run the old spec. The only leniency
    is `catalogue_versions`, compared per name the consumer pinned: a version published between the
    first request and the retry changes what the gate would pin now, not what was asked.
    """
    sent = asked.model_dump(mode="json")
    held = frozen.model_dump(mode="json")
    differing: list[str] = []
    for field, value in sent.items():
        if field == "catalogue_versions":
            pinned = held.get(field) or {}
            if any(pinned.get(name) != version for name, version in value.items()):
                differing.append(field)
            continue
        if held.get(field) != value:
            differing.append(field)
    return sorted(differing)


@app.get("/runs")
def list_runs() -> dict[str, list[str]]:
    """Every run this deployment accepted, read off the frozen specs. Ids only: a phase per run is a
    listing per run, and `GET /runs/{id}` answers it for the one a consumer asks about."""
    from redteam_api import deps
    from redteam_store import layout

    found = sorted(
        run_id
        for key in deps.store().list_prefix(layout.RUNS + "/")
        if (run_id := layout.parse_spec_key(key)) is not None
    )
    return {"runs": found}


@app.get("/runs/{run_id}", response_model=RunStatusResponse)
def get_run(run_id: str) -> RunStatusResponse:
    """The run's phase from the store, and whether the platform still has a process for it."""
    from redteam_api import deps
    from redteam_api.status import derive
    from redteam_store.interface import ObjectNotFound

    try:
        planned = deps.planned_units(run_id)
        status = derive(deps.store(), run_id, planned, deps.dispatcher().status(run_id))
    except (KeyError, ObjectNotFound) as exc:
        raise HTTPException(status_code=404, detail=f"no run {run_id}") from exc
    return RunStatusResponse(
        run_id=status.run_id,
        phase=status.phase,
        runner=status.runner,
        stalled=status.stalled,
        planned=status.planned,
        closed=status.closed,
        failed=status.failed,
        pending=status.pending,
    )


@app.get("/runs/{run_id}/result")
def get_result(run_id: str) -> dict[str, Any]:
    """The manifest: the one file that says whether a run is usable, and where its artifacts are."""
    from redteam_api import deps
    from redteam_store import layout
    from redteam_store.interface import ObjectNotFound

    try:
        return dict(json.loads(deps.store().get(layout.manifest(run_id))))
    except ObjectNotFound as exc:
        raise HTTPException(status_code=404, detail=f"no result for {run_id} yet") from exc


@app.post("/runs/{run_id}:resume", status_code=202, response_model=Relaunched)
def resume_run(run_id: str) -> Relaunched:
    """Launch a runner for a frozen run again. It resumes from the difference: nothing closed is
    re-executed, and a run already closed has nothing to do.

    The remedy for a stalled run -- the store says the attack is under way and the platform says
    nothing is running it -- and for a failed attempt the platform gave up relaunching.
    """
    from redteam_api import deps
    from redteam_store import layout
    from redteam_store.interface import ObjectNotFound

    try:
        spec = RunSpec.model_validate_json(deps.store().get(layout.spec(run_id)))
    except ObjectNotFound as exc:
        raise HTTPException(status_code=404, detail=f"no run {run_id}") from exc
    if deps.store().exists(layout.manifest(run_id)):
        raise HTTPException(status_code=409, detail=f"run {run_id!r} already closed")
    launched = _launch(spec)
    return Relaunched(run_id=run_id, launched=launched, runner=deps.dispatcher().status(run_id))


# ---- catalogue bundles --------------------------------------------------------------------------


class BundleRequest(BaseModel):
    """A catalogue bundle as a request body: the same four files a bundle directory holds."""

    name: str
    catalogue: dict[str, Any]
    contract: dict[str, Any]
    """The behavioural contract the catalogue's plugins charge. Required: a catalogue whose
    plugins charge principles nobody declared cannot be graded."""

    needs_base: list[str] | None = None
    """The grounding sidecar's list: strategies that need a knowledge base although their phrasing
    does not say so. Publishing refuses a premise-bearing strategy left out."""

    delivery: dict[str, Any] | None = None
    """The delivery sidecar's block: which strategies are conversations, through which attacker
    id, bounded how. A key the sidecar does not know is refused rather than dropped."""


class PublishedBundle(BaseModel):
    name: str
    version: int
    key: str
    digest: str
    contract_digest: str
    principles: int
    delivered: tuple[str, ...] = Field(default_factory=tuple)
    created: bool = True
    """False when exactly this bundle was already the newest version: nothing was written."""


class CheckedBundle(BaseModel):
    name: str
    principles: int
    strategies: int
    needs_base: tuple[str, ...]
    delivered: tuple[str, ...]


def _bundle(request: BundleRequest) -> Any:
    """The request as the catalogue package's `Bundle`, or a 400 saying which file is malformed."""
    from gaussia.schemas.roastme import Catalogue

    from redteam_catalogue.bundle import Bundle
    from redteam_contracts.contract import parse_contract_spec

    try:
        catalogue = Catalogue.model_validate(request.catalogue)
    except ValidationError as malformed:
        raise HTTPException(
            status_code=400, detail=f"catalogue.json is malformed: {malformed}"
        ) from malformed
    try:
        contract = parse_contract_spec(json.dumps(request.contract))
    except ValueError as malformed:
        raise HTTPException(
            status_code=400, detail=f"contract.json is malformed: {malformed}"
        ) from malformed
    return Bundle(
        catalogue=catalogue,
        contract=contract,
        needs_base=frozenset(request.needs_base or ()),
        delivery=request.delivery,
    )


@app.post("/catalogues:validate", response_model=CheckedBundle)
def validate_bundle(request: BundleRequest) -> CheckedBundle:
    """Everything publishing checks, with nothing written: the six semantic rejections against the
    bundle's own contract, the grounding against the phrasings, the delivery against the
    strategies."""
    from redteam_catalogue import assets
    from redteam_catalogue.engines import declared_engines

    bundle = _bundle(request)
    try:
        checked = assets.check(
            bundle.catalogue,
            bundle.contract,
            *declared_engines(bundle.entity_kinds),
            needs_base=sorted(assets.needs_a_base(bundle.catalogue, bundle.needs_base)),
            delivery=bundle.delivery,
        )
    except ValueError as refused:
        raise HTTPException(status_code=422, detail=str(refused)) from refused
    return CheckedBundle(
        name=request.name,
        principles=len(bundle.contract.principles),
        strategies=len(bundle.catalogue.strategies),
        needs_base=tuple(sorted(checked.needs_base)),
        delivered=checked.conducted,
    )


@app.post("/catalogues", status_code=201, response_model=PublishedBundle)
def publish_bundle(request: BundleRequest, response: Response) -> PublishedBundle:
    """Validate and write the next version of a bundle: catalogue, contract and sidecars, as one
    version.

    Versioned rather than overwritten: the store only appends, and a catalogue replaced in place
    would make every finished run's provenance unreadable. `201` when a version was written; `200`
    when exactly this bundle was already the newest version, which names that version and writes
    nothing -- a seed that runs twice publishes once.
    """
    from redteam_api import deps
    from redteam_catalogue import assets
    from redteam_catalogue.engines import declared_engines
    from redteam_store.interface import ObjectAlreadyExists

    bundle = _bundle(request)
    try:
        published = assets.publish(
            deps.store(),
            request.name,
            bundle.catalogue,
            bundle.contract,
            *declared_engines(bundle.entity_kinds),
            needs_base=sorted(assets.needs_a_base(bundle.catalogue, bundle.needs_base)),
            delivery=bundle.delivery,
        )
    except ValueError as refused:
        raise HTTPException(status_code=422, detail=str(refused)) from refused
    except ObjectAlreadyExists as raced:
        raise HTTPException(status_code=409, detail=str(raced)) from raced
    if not published.created:
        response.status_code = HTTPStatus.OK
    return PublishedBundle(
        name=published.name,
        version=published.version,
        key=published.key,
        digest=published.digest,
        contract_digest=published.contract_digest,
        principles=published.principles,
        delivered=tuple(published.delivered),
        created=published.created,
    )


@app.get("/catalogues")
def list_catalogues() -> dict[str, list[int]]:
    """Every published catalogue and its versions, read off one listing of the store."""
    from redteam_api import deps
    from redteam_store import layout

    found: dict[str, list[int]] = {}
    for key in deps.store().list_prefix(layout.catalogues_prefix() + "/"):
        parsed = layout.parse_catalogue_key(key)
        if parsed is not None:
            found.setdefault(parsed[0], []).append(parsed[1])
    return {name: sorted(versions) for name, versions in sorted(found.items())}


# ---- priors and probe sets ----------------------------------------------------------------------


class PriorRequest(BaseModel):
    name: str
    phrasings: list[str]
    """What real users of this assistant actually send, in the register they send it. An invented
    pool measures our imagination rather than the assistant, and an empty one is refused."""


class PublishedPrior(BaseModel):
    name: str
    version: int
    key: str
    digest: str
    size: int
    created: bool


@app.post("/priors", status_code=201, response_model=PublishedPrior)
def publish_prior(request: PriorRequest, response: Response) -> PublishedPrior:
    """The next version of a natural-query prior. `201` when written, `200` when exactly this pool
    was already the newest version."""
    from redteam_api import deps
    from redteam_store.interface import ObjectAlreadyExists
    from redteam_store.priors import EmptyPrior, publish

    try:
        published = publish(deps.store(), request.name, request.phrasings)
    except EmptyPrior as refused:
        raise HTTPException(status_code=422, detail=str(refused)) from refused
    except ObjectAlreadyExists as raced:
        raise HTTPException(status_code=409, detail=str(raced)) from raced
    if not published.created:
        response.status_code = HTTPStatus.OK
    return PublishedPrior(
        name=published.name,
        version=published.version,
        key=published.key,
        digest=published.digest,
        size=published.size,
        created=published.created,
    )


@app.get("/priors")
def list_priors() -> dict[str, list[int]]:
    from redteam_api import deps
    from redteam_store import priors

    store = deps.store()
    return {name: list(priors.versions(store, name)) for name in sorted(priors.names(store))}


@app.get("/probes/{digest}")
def get_probes(digest: str) -> list[dict[str, Any]]:
    """One probe set, by content. What a run's `probes.json` points at."""
    from redteam_api import deps
    from redteam_store import layout
    from redteam_store.interface import ObjectNotFound

    try:
        key = layout.blob(digest)
    except ValueError as malformed:
        raise HTTPException(status_code=400, detail=str(malformed)) from malformed
    try:
        return [dict(p) for p in json.loads(deps.store().get(key))]
    except ObjectNotFound as exc:
        raise HTTPException(status_code=404, detail=f"no probe set {digest}") from exc


def cli() -> None:
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8080)
