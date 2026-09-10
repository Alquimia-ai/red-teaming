"""One run's probe set: generated in the runner's process, written once, pinned by `probes.json`.

**One pull per run, and the brain dies with the generation.** That is not a cache and must never
become one: the brain is pulled into a temporary directory, read, and discarded, so the client's
knowledge is resident for exactly as long as reading it takes.

What is written is the blob by digest -- shared with every other run over the same base and
catalogue -- and the run's own `probes.json`, whose existence is what pins the run's set: a runner
that finds it reads the digest from there and never generates again, so a catalogue published
between two launches of one run cannot change the plan.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from typing import Any

from redteam_contracts.kb import KnowledgeBase
from redteam_probes.generation import generate_all, no_base
from redteam_probes.request import GenerationReport, GenerationRequest
from redteam_store import layout
from redteam_store.codec import encode_json
from redteam_store.interface import ObjectAlreadyExists, ObjectNotFound, ObjectStore


def existing_report(store: ObjectStore, run_id: str) -> GenerationReport | None:
    """What a run's `probes.json` records, or None while generation has not closed.

    A pointer written before the record carried a report has only `digest` and `count`; it still
    pins the run's set and is answered rather than refused, so a run accepted before that change
    stays resumable.
    """
    try:
        pointer = json.loads(store.get(layout.probes(run_id)))
    except ObjectNotFound:
        return None
    report = pointer.get("report")
    if isinstance(report, dict):
        return GenerationReport.model_validate({**report, "skipped_existing": True})
    return GenerationReport(
        probes_digest=str(pointer["digest"]),
        probe_count=int(pointer["count"]),
        skipped_existing=True,
    )


def generate_for(
    store: ObjectStore,
    request: GenerationRequest,
    *,
    model: Any | None = None,
    registry: Any | None = None,
    knowledge_base: KnowledgeBase | None = None,
) -> GenerationReport:
    """The run's probe set: read back when it is already pinned, generated and written otherwise.

    Args:
        store: The run's store.
        request: What the frozen spec asks generation for.
        model: The generator the run declared, already built; None when it declared none.
        registry: The registry client a brain is pulled through. Required when the request names a
            `kb_ref` and no `knowledge_base` is handed in.
        knowledge_base: A base already open, for a rehearsal or a test. Skips the pull.
    """
    pinned = existing_report(store, request.run_id)
    if pinned is not None:
        return pinned
    return asyncio.run(_generate(store, request, model, registry, knowledge_base))


async def _generate(
    store: ObjectStore,
    request: GenerationRequest,
    model: Any | None,
    registry: Any | None,
    knowledge_base: KnowledgeBase | None,
) -> GenerationReport:
    """Generate, write the blob and the run's pointer, and return the report.

    Async for one reason and it is the only await on the path: pulling a brain. Generation happens
    **inside** that context, so the client's knowledge is resident for exactly as long as reading it
    takes.
    """
    if request.kb_ref is None:
        produced = generate_all(store, request, no_base(), model=model)
    elif knowledge_base is not None:
        produced = generate_all(store, request, knowledge_base, model=model)
    else:
        if registry is None:
            raise ValueError(
                f"run {request.run_id!r} names a knowledge base and no registry client was given "
                f"to pull it through"
            )
        from redteam_knowledge.boltzmann_kb import pulled_brain

        async with pulled_brain(request.kb_ref, registry, subjects=request.kb_subjects) as brain:
            produced = generate_all(store, request, brain, model=model)

    payload = encode_json([p.model_dump(mode="json") for p in produced.probes])
    digest = produced.digest

    # Two runs over one base and one catalogue produce the same set, so the blob is written once and
    # the second finds it there. What the second skips is the write, never the generation: the
    # digest is of what was generated, so it is known only after generating. Asked before writing,
    # or `exists` answers about this run's own write and says "this cost nothing" unconditionally.
    skipped = store.exists(layout.blob(digest))
    if not skipped:
        try:
            store.put(layout.blob(digest), payload, content_type="application/json")
        except ObjectAlreadyExists:
            # A twin landed between the check and the write. Same digest is same content, so its
            # bytes are these bytes and there is nothing to reconcile.
            skipped = True

    report = GenerationReport(
        probes_digest=digest,
        probe_count=len(produced.probes),
        catalogue_versions=produced.catalogue_versions,
        contract_digest=produced.contract_digest,
        degenerate_strategies=produced.degenerate,
        engines_ran=produced.engines,
        unresolved_entities={key: list(values) for key, values in produced.unresolved.items()},
        unverified_probes=produced.unverified,
        grounded=produced.grounded,
        strategies_set_aside=produced.set_aside,
        skipped_existing=skipped,
    )
    # The pointer is the run's generation record, written once. Its existence is what pins the
    # set, so a twin that got there first wins and this run's identical work is discarded rather
    # than overwriting it.
    with contextlib.suppress(ObjectAlreadyExists):
        store.put(
            layout.probes(request.run_id),
            encode_json(
                {
                    "digest": digest,
                    "count": len(produced.probes),
                    "report": report.model_dump(mode="json", exclude={"skipped_existing"}),
                }
            ),
            content_type="application/json",
        )
    return report


REFUSED = "refused"
"""The request has to change. A catalogue that fails one of the six rejections, a construction whose
context the spec never declared, a corpus that cannot ground what it was asked to, catalogues that
disagree on the contract. Retrying it unchanged changes nothing."""

MISSING = "missing"
"""Something the request named is not published: a catalogue, a version of one, its contract."""

UPSTREAM = "upstream"
"""Something outside answered badly or not at all -- the registry holding the brain, a model
provider. Worth retrying; nothing about the request is wrong."""

UNKNOWN = "unknown"
"""Everything else, which is a bug here rather than a fact about the request."""


def classify(refused: BaseException) -> str:
    """What kind of failure this was, so a reader knows whether to change the request or retry it.

    By exception type rather than by message, and grouped by what the reader can do about it --
    those are the only two answers that differ.
    """
    from redteam_catalogue.assets import CatalogueNotFound
    from redteam_catalogue.documents import UngroundableCorpus
    from redteam_catalogue.premises import ContextRequired

    if isinstance(refused, ContextRequired | UngroundableCorpus):
        return REFUSED
    if isinstance(refused, CatalogueNotFound | FileNotFoundError):
        return MISSING
    if isinstance(refused, KeyError):
        # `ContractMissing` and the store's own misses are KeyErrors, and so is a version nobody
        # published.
        return MISSING
    if isinstance(refused, ValueError):
        # gaussia's six rejections, and every refusal this repo raises as one.
        return REFUSED
    if isinstance(refused, ConnectionError | TimeoutError | OSError):
        return UPSTREAM
    return UNKNOWN
