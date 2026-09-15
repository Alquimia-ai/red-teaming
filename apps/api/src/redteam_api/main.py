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
from pydantic import BaseModel, Field

from redteam_api.validation import ValidationFailure, resolve_versions, validate
from redteam_contracts.catalogue import CatalogueDocument
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
    summary="Accepts runs, freezes the spec, launches a runner, publishes catalogue documents and "
    "priors, and answers state from the store and the platform.",
)


class AcceptedRun(BaseModel):
    realism_prior: str | None = None
    realism_prior_version: int | None = None
    realism_prior_digest: str | None = None
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

    realism_prior: str | None = None
    realism_prior_version: int | None = None
    realism_prior_digest: str | None = None
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
    from redteam_store import priors
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
            brain_required=selection.requires_brain,
        )
        if spec.realism_prior is None and (
            spec.realism_prior_version is not None or spec.realism_prior_digest is not None
        ):
            raise ValueError("prior version and digest require realism_prior")
        prior = (
            priors.resolve(
                deps.store(),
                spec.realism_prior,
                spec.realism_prior_version,
                spec.realism_prior_digest,
            )
            if spec.realism_prior
            else None
        )
        pinned = spec.model_copy(
            update={
                "catalogue_versions": versions,
                "realism_prior_version": prior.version if prior else None,
                "realism_prior_digest": prior.digest if prior else None,
            }
        )
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
    except (
        ValidationFailure,
        EmptySelection,
        NothingToGenerate,
        ValueError,
        priors.PriorNotFound,
    ) as refused:
        raise HTTPException(status_code=400, detail=str(refused)) from refused
    return pinned, contract_digest


@app.post("/runs:validate", response_model=ValidatedRun)
def validate_run(spec: RunSpec) -> ValidatedRun:
    """The gate alone: what `POST /runs` would freeze and launch, with nothing written."""
    from redteam_api import deps

    pinned, contract_digest = _gate(spec)
    return ValidatedRun(
        run_id=pinned.run_id,
        realism_prior=pinned.realism_prior,
        realism_prior_version=pinned.realism_prior_version,
        realism_prior_digest=pinned.realism_prior_digest,
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
    from redteam_contracts.run_id import check
    from redteam_store import layout
    from redteam_store.interface import ObjectAlreadyExists

    try:
        check(spec.run_id)
    except ValueError as invalid:
        raise HTTPException(status_code=400, detail=str(invalid)) from invalid

    pinned = _existing_run(spec)
    if pinned is None:
        try:
            pinned, _ = _gate(spec)
        except HTTPException:
            # Another request can freeze this id while the current catalogue is changing.
            pinned = _existing_run(spec)
            if pinned is None:
                raise
        else:
            try:
                deps.store().put(
                    layout.spec(pinned.run_id),
                    pinned.model_dump_json(indent=2).encode(),
                    content_type="application/json",
                )
            except ObjectAlreadyExists:
                pinned = _existing_run(spec)
                assert pinned is not None  # an append-only spec cannot disappear

    launched = _launch(pinned)
    return AcceptedRun(
        run_id=pinned.run_id,
        realism_prior=pinned.realism_prior,
        realism_prior_version=pinned.realism_prior_version,
        realism_prior_digest=pinned.realism_prior_digest,
        result_location=layout.manifest(pinned.run_id),
        catalogue_versions=dict(pinned.catalogue_versions),
        launched=launched,
    )


def _existing_run(asked: RunSpec) -> RunSpec | None:
    """Retries compare against the accepted identity, without consulting mutable latest assets."""
    from redteam_api import deps
    from redteam_store import layout
    from redteam_store.interface import ObjectNotFound

    try:
        frozen = RunSpec.model_validate_json(deps.store().get(layout.spec(asked.run_id)))
    except ObjectNotFound:
        return None
    differing = _fields_that_differ(asked, frozen)
    if differing:
        raise HTTPException(
            status_code=409,
            detail=f"run {asked.run_id!r} is already frozen with a different spec; "
            f"the retry differs in {differing}. A change needs a new run id.",
        )
    return frozen


def _launch(spec: RunSpec) -> bool:
    """Ask the platform for one runner. False when it refused a second one for a run whose first is
    still running -- the uniqueness invariant working, not an error."""
    from redteam_api import deps
    from redteam_dispatch import AlreadyRunning, DispatchError
    from redteam_store import layout

    if deps.store().exists(layout.manifest(spec.run_id)):
        return False
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
        if field in {"realism_prior_version", "realism_prior_digest"} and value is None:
            continue
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


# ---- catalogue documents ------------------------------------------------------------------------


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
    requires_brain: tuple[str, ...]
    interaction_modes: dict[str, str]


@app.post("/catalogues:validate", response_model=CheckedBundle)
def validate_bundle(request: CatalogueDocument) -> CheckedBundle:
    """Validate one complete catalogue document without writing it."""
    from redteam_catalogue import assets

    try:
        assets.check_document(request)
    except ValueError as refused:
        raise HTTPException(status_code=422, detail=str(refused)) from refused
    return CheckedBundle(
        name=request.name,
        principles=len(assets.contract_of(request).principles),
        strategies=len(request.strategies),
        requires_brain=tuple(sorted(s.id for s in request.strategies if s.requires_brain)),
        interaction_modes={s.id: s.interaction.mode for s in request.strategies},
    )


@app.post("/catalogues", status_code=201, response_model=PublishedBundle)
def publish_bundle(request: CatalogueDocument, response: Response) -> PublishedBundle:
    """Validate and write the next immutable version of one catalogue document.

    Versioned rather than overwritten: the store only appends, and a catalogue replaced in place
    would make every finished run's provenance unreadable. `201` when a version was written; `200`
    when exactly this bundle was already the newest version, which names that version and writes
    nothing -- a seed that runs twice publishes once.
    """
    from redteam_api import deps
    from redteam_catalogue import assets
    from redteam_store.interface import ObjectAlreadyExists

    try:
        published = assets.publish_document(deps.store(), request)
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
