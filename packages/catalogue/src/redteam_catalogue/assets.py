"""Catalogue bundles, published to the store and read from it.

A catalogue is the client's own risk taxonomy: which families of failure to test and which
interaction patterns present them, with the contract its plugins charge beside it. It is the asset,
and an asset baked into an image is one that ships on our release cadence rather than on the
engagement's.

**Versioned explicitly, because the store only appends.** There is no `current` pointer to move, so
publishing writes the next version and a sorted listing answers "the newest". A catalogue that could
be overwritten in place would make every finished run's provenance unreadable, since the name it
recorded now resolves to something else.

**Validated at publish, not at generation.** The six semantic rejections are decidable from the
catalogue, the contract and the configured engines, and running them here means a malformed
catalogue costs one rejected request instead of a run that generates an empty probe set with no
error -- which gaussia calls the failure mode hardest to notice.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from gaussia.schemas.roastme import Catalogue

from redteam_catalogue.contract import validation_contract
from redteam_catalogue.validate import validate
from redteam_contracts.catalogue import (
    AdaptiveMultiTurn,
    CatalogueDocument,
    ScriptedMultiTurn,
    SingleTurn,
)
from redteam_contracts.contract import ContractSpec, as_raw, parse_contract_spec
from redteam_store import contract as contract_store
from redteam_store import delivery as delivery_store
from redteam_store import grounding as grounding_store
from redteam_store import layout
from redteam_store.interface import ObjectAlreadyExists, ObjectNotFound, ObjectStore
from redteam_store.versioned import CLAIM_ATTEMPTS

FIRST_VERSION = 1


def load_document(store: ObjectStore, name: str, version: int | None = None) -> CatalogueDocument:
    """Load one schema-v2 catalogue document from its immutable object."""
    resolved = latest(store, name) if version is None else version
    try:
        raw = store.get(layout.catalogue(name, resolved))
    except ObjectNotFound as missing:
        raise CatalogueNotFound(f"{name} v{resolved}") from missing
    document = CatalogueDocument.model_validate_json(raw)
    if document.name != name:
        raise ValueError(
            f"catalogue key {name!r} contains a document named {document.name!r}"
        )
    return document


def as_catalogue(document: CatalogueDocument, language: str | None = None) -> Catalogue:
    """Resolve interaction text and adapt the portable document to the probe library schema."""
    strategies: list[dict[str, Any]] = []
    for strategy in document.strategies:
        if language is None:
            interaction = strategy.interaction
            values = (
                interaction.messages
                if isinstance(interaction, ScriptedMultiTurn)
                else (interaction.opening,)
                if isinstance(interaction, AdaptiveMultiTurn)
                else (interaction.prompt,)
            )
            first = values[0]
            phrasing = first if isinstance(first, str) else next(iter(first.values()))
        else:
            phrasing = strategy.messages(language)[0]
        strategies.append(
            {
                "id": strategy.id,
                "name": strategy.name,
                "description": strategy.description,
                "plugin": strategy.plugin,
                "entity_kind": strategy.entity_kind,
                "transform": strategy.transform,
                "doc": strategy.doc,
                "phrasing_hint": phrasing,
            }
        )
    return Catalogue.model_validate(
        {
            "plugins": [plugin.model_dump(mode="json") for plugin in document.plugins],
            "strategies": strategies,
        }
    )


def selected_document(
    document: CatalogueDocument,
    plugins: Sequence[str] = (),
    strategies: Sequence[str] = (),
) -> CatalogueDocument:
    """Apply run selectors while retaining controls for the selected attacks."""
    if not plugins and not strategies:
        return document
    wanted_plugins = frozenset(plugins)
    wanted_strategies = frozenset(strategies)
    attacks = tuple(
        strategy
        for strategy in document.strategies
        if strategy.plugin is not None
        and (
            (not wanted_strategies or strategy.id in wanted_strategies)
            and (not wanted_plugins or strategy.plugin in wanted_plugins)
        )
    )
    if not attacks:
        raise EmptySelection(
            f"plugins={sorted(wanted_plugins)} strategies={sorted(wanted_strategies)} select no "
            "strategy that attacks anything"
        )
    requirements = {strategy.requires_brain for strategy in attacks}
    kept = attacks + tuple(
        strategy
        for strategy in document.strategies
        if strategy.plugin is None and strategy.requires_brain in requirements
    )
    referenced = {strategy.plugin for strategy in kept if strategy.plugin}
    return document.model_copy(
        update={
            "strategies": kept,
            "plugins": tuple(plugin for plugin in document.plugins if plugin.id in referenced),
        }
    )


def contract_of(document: CatalogueDocument) -> ContractSpec:
    return parse_contract_spec(json.dumps(document.contract))


def shared_contract(
    store: ObjectStore, selected_versions: Mapping[str, int]
) -> tuple[ContractSpec, str]:
    """Return the identical embedded contract carried by every selected document."""
    if not selected_versions:
        raise ValueError("a run names at least one catalogue; none was given")
    documents = {
        f"{name} v{version}": load_document(store, name, version)
        for name, version in selected_versions.items()
    }
    encoded = {
        label: contract_store.encode(document.contract) for label, document in documents.items()
    }
    digests = {label: _digest(payload) for label, payload in encoded.items()}
    if len(set(digests.values())) != 1:
        from redteam_store.contract import ContractMismatch

        raise ContractMismatch(
            f"the selected catalogues carry different embedded contracts: {digests}"
        )
    first = next(iter(documents.values()))
    return contract_of(first), next(iter(digests.values()))


_SIDECARS: tuple[Callable[[str, int], str], ...] = (
    layout.catalogue_contract,
    layout.catalogue_grounding,
    layout.catalogue_delivery,
)
"""How each sidecar's key is spelled, in write order. The contract comes first and is never absent.

A tuple rather than special cases because everything below treats them identically -- written
before the catalogue, compared for identity, walked past when orphaned.
"""

_PREMISE_SLOT = "{premise}"
"""What makes a phrasing need a premise, and therefore a base to draw one from.

gaussia's marker, restated rather than imported: it is private to gaussia's particularisation
module, and reaching under an underscore for it would couple this to a name its owner has not
published. The string itself is as public as a schema gets -- every catalogue ever written carries
it.
"""


class CatalogueNotFound(KeyError):
    def __init__(self, name: str) -> None:
        super().__init__(f"no catalogue published under the name {name!r}")
        self.name = name


@dataclass(frozen=True)
class Published:
    """Where a bundle landed, and what it is."""

    name: str
    version: int
    key: str
    digest: str
    """The catalogue's own digest."""

    contract_digest: str
    """The contract sidecar's digest: what two catalogues of one run are compared by."""

    principles: int
    created: bool = True
    """False when this exact catalogue, with these exact sidecars, was already the newest version:
    nothing was written, and the version named is where it lives."""

    delivered: tuple[str, ...] = ()
    """The strategies whose delivery the sidecar declares, by id, at the same version."""


def check_document(document: CatalogueDocument) -> None:
    """Validate the complete schema-v2 document against contract, engines, and transforms."""
    from redteam_catalogue.engines import declared_engines
    from redteam_catalogue.premises import descriptor

    incompatible = sorted(
        strategy.id
        for strategy in document.strategies
        if (declared := descriptor(strategy.transform)) is not None
        and declared.needs_brain
        and not strategy.requires_brain
    )
    if incompatible:
        raise ValueError(
            f"strategies {incompatible} declare transforms that need a brain while "
            "`requires_brain` is false"
        )
    catalogue = as_catalogue(document)
    contract = contract_of(document)
    validate(
        catalogue,
        validation_contract(contract),
        *declared_engines(tuple(sorted({s.entity_kind for s in document.strategies}))),
    )


def publish_document(store: ObjectStore, document: CatalogueDocument) -> Published:
    """Publish one canonical document under the next append-only version."""
    check_document(document)
    payload = json.dumps(
        document.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    contract_bytes = contract_store.encode(document.contract)
    delivered = tuple(
        sorted(
            strategy.id
            for strategy in document.strategies
            if not isinstance(strategy.interaction, SingleTurn)
        )
    )

    def answer(version: int, *, created: bool) -> Published:
        return Published(
            name=document.name,
            version=version,
            key=layout.catalogue(document.name, version),
            digest=_digest(payload),
            contract_digest=_digest(contract_bytes),
            principles=len(contract_of(document).principles),
            created=created,
            delivered=delivered,
        )

    current = versions(store, document.name)
    if current and store.get(layout.catalogue(document.name, current[-1])) == payload:
        return answer(current[-1], created=False)
    for _ in range(CLAIM_ATTEMPTS):
        current = versions(store, document.name)
        version = current[-1] + 1 if current else FIRST_VERSION
        key = layout.catalogue(document.name, version)
        try:
            store.put(key, payload, content_type="application/json")
        except ObjectAlreadyExists:
            if store.get(key) == payload:
                return answer(version, created=False)
            continue
        return answer(version, created=True)
    raise ObjectAlreadyExists(layout.catalogue(document.name, version))


def names(store: ObjectStore) -> frozenset[str]:
    """Every catalogue name that has at least one published version."""
    found = set()
    for key in store.list_prefix(layout.catalogues_prefix() + "/"):
        parsed = layout.parse_catalogue_key(key)
        if parsed is not None:
            found.add(parsed[0])
    return frozenset(found)


def versions(store: ObjectStore, name: str) -> tuple[int, ...]:
    """The published versions of one catalogue, ascending."""
    return tuple(
        sorted(
            parsed[1]
            for key in store.list_prefix(layout.catalogue_prefix(name) + "/")
            if (parsed := layout.parse_catalogue_key(key)) is not None
        )
    )


def latest(store: ObjectStore, name: str) -> int:
    """The newest published version, or refuse.

    Read off a sorted listing rather than from a timestamp, because the store exposes none -- and a
    version number the publisher assigned is a fact anybody can check against the keys.
    """
    published = versions(store, name)
    if not published:
        raise CatalogueNotFound(name)
    return published[-1]


def load(store: ObjectStore, name: str, version: int | None = None) -> Catalogue:
    """One catalogue, by name and version. The newest when no version is named.

    A run resolves the version at acceptance and freezes it, so nothing published afterwards can
    change what a finished run measured.
    """
    resolved = latest(store, name) if version is None else version
    try:
        raw = store.get(layout.catalogue(name, resolved))
    except ObjectNotFound as missing:
        raise CatalogueNotFound(f"{name} v{resolved}") from missing
    return Catalogue.model_validate(json.loads(raw))


class EmptySelection(ValueError):
    """The plugins and strategies a run named leave nothing to generate from.

    Refused rather than run. A run that narrows to nothing produces an empty probe set, and an
    empty probe set measures nothing while every downstream artifact reports itself as complete.
    """


class GroundingMisdeclared(ValueError):
    """A strategy leans on a premise and the catalogue did not declare that it needs a base.

    Which strategies need a knowledge base is the catalogue's own statement, made in the grounding
    sidecar. This is what happens when that statement is incomplete: the strategy's phrasing carries
    `{premise}`, so it plainly needs a base, and leaving it undeclared would let a run with no brain
    generate it -- with the slot removed, which turns `"What does {premise} cover?"` into
    `"What does cover?"` and measures the assistant's tolerance for malformed input instead of
    anything the catalogue meant to test.

    Raised at publish, before a byte is written, so the cost is one rejected request rather than a
    run against somebody's assistant.
    """

    def __init__(self, undeclared: Sequence[str]) -> None:
        super().__init__(
            f"{sorted(undeclared)} lean on a premise and are not declared as needing a knowledge "
            f"base. A run without one would send their phrasing with the {_PREMISE_SLOT} slot "
            f"removed, which is not a question anybody asks. Add them to the grounding sidecar's "
            f"`needs_base`, or write phrasings that stand without a premise."
        )
        self.undeclared = tuple(sorted(undeclared))


class DeliveryMisdeclared(ValueError):
    """The delivery sidecar names a strategy the catalogue does not carry.

    A declaration about nothing. The rest of what a delivery may get wrong -- an unknown key, `many`
    with no attacker, a bound of one -- is refused by `redteam_store.delivery.normalise` before this
    is reached, because those are facts about the declaration alone and this one needs the
    catalogue.
    """

    def __init__(self, unknown: Sequence[str]) -> None:
        super().__init__(
            f"the delivery sidecar names strategies the catalogue does not carry: {sorted(unknown)}"
        )
        self.unknown = tuple(sorted(unknown))


class NothingToGenerate(ValueError):
    """This run's catalogue carries no strategy the run can generate from.

    Refused for the same reason `EmptySelection` is: what it would otherwise produce is an empty
    probe set that every downstream artifact reports as a complete run. The entry gate refuses the
    brainless case before the run is accepted; reaching either case here means a request that
    bypassed it.
    """

    def __init__(self, name: str, *, grounded: bool, left_out: frozenset[str]) -> None:
        if grounded:
            super().__init__(
                f"catalogue {name!r} carries no strategy that leans on a premise -- "
                f"{sorted(left_out)} all stand without one -- and this run names a brain. A "
                f"premise would be appended to each of them rather than placed in it. Name a "
                f"catalogue written for a knowledge base, or drop the brain."
            )
        else:
            super().__init__(
                f"catalogue {name!r} carries no strategy that stands without a premise: "
                f"{sorted(left_out)} all lean on one, and this run names no brain. Attach a "
                f"brain, or name a catalogue carrying strategies that need none."
            )
        self.name = name
        self.grounded = grounded
        self.left_out = left_out


def needs_a_base(catalogue: Catalogue, declared: frozenset[str] = frozenset()) -> frozenset[str]:
    """Which strategies of a catalogue cannot be generated without a knowledge base.

    Two sources. `declared` is the grounding sidecar, which is where a catalogue states this and
    which publishing requires to be complete. The slots are added to it because a phrasing carrying
    `{premise}` needs a base whether or not the sidecar mentions it; for anything published here,
    the two agree by construction.

    The same rule `redteam_store.grounding.needs_a_base` applies to the stored JSON. They are on
    opposite sides of a line the store may not cross: it does not depend on gaussia, so it cannot be
    handed a `Catalogue`.
    """
    return frozenset(
        strategy.id
        for strategy in catalogue.strategies
        if _PREMISE_SLOT in strategy.phrasing_hint or strategy.id in declared
    )


def generatable(
    catalogue: Catalogue,
    *,
    grounded: bool,
    declared: frozenset[str] = frozenset(),
    name: str = "",
) -> Catalogue:
    """The half of a catalogue this run can generate from, decided by whether it has a base.

    A strategy that leans on a premise runs **only** with a knowledge base, and one that stands
    without a premise runs **only** without: the two are not interchangeable in either direction,
    and both mismatches produce a malformed probe. Without a base, `"What does {premise} cover?"`
    reaches the assistant as `"What does cover?"`. With one, `"Are you a person or a program?"`
    reaches it as `"Are you a person or a program?: Plan Andes Total"` -- an interrogative never
    closed, punctuated where nobody punctuates.

    So one catalogue can carry both kinds and each run generates its own half. Nothing has to
    declare which is which, because the phrasing already does.

    Not `narrow`, deliberately: its rule that controls always survive is right for a selector and
    wrong here, since a control whose phrasing carries `{premise}` has no premise to put in it
    either. A control written for this run's shape is kept like any other strategy.

    What is left out is reported by the caller rather than swallowed.

    Raises:
        NothingToGenerate: Every strategy belongs to the other half, or nothing but controls
            survives. A run of controls alone has a denominator and nothing to divide into it. It
            also keeps the result a valid `Catalogue`, which requires at least one plugin --
            `model_copy` does not revalidate, so an unreferenced-plugin list would otherwise travel
            as a model nothing would refuse.
    """
    needs = needs_a_base(catalogue, declared)
    kept = [strategy for strategy in catalogue.strategies if (strategy.id in needs) is grounded]
    referenced = {strategy.plugin for strategy in kept if strategy.plugin}
    if not referenced:
        left_out = frozenset(strategy.id for strategy in catalogue.strategies)
        raise NothingToGenerate(name, grounded=grounded, left_out=left_out)
    return catalogue.model_copy(
        update={
            "strategies": kept,
            "plugins": [plugin for plugin in catalogue.plugins if plugin.id in referenced],
        }
    )


def narrow(
    catalogue: Catalogue,
    plugins: Sequence[str] = (),
    strategies: Sequence[str] = (),
) -> Catalogue:
    """The part of a catalogue a run asked for.

    Naming neither leaves the catalogue whole, which is the ordinary case. Naming either is how a
    run tests one risk family without publishing a second catalogue for it.

    **Controls always survive.** A strategy with no plugin is the only thing separating "the
    assistant is careful" from "the questions were easy", so narrowing to a plugin keeps the
    controls that make its rate readable.

    Raises:
        EmptySelection: Nothing survives, or nothing but controls does.
    """
    if not plugins and not strategies:
        return catalogue

    wanted_plugins = frozenset(plugins)
    wanted_strategies = frozenset(strategies)
    kept = [
        strategy
        for strategy in catalogue.strategies
        if strategy.plugin is None
        or (
            (not wanted_strategies or strategy.id in wanted_strategies)
            and (not wanted_plugins or strategy.plugin in wanted_plugins)
        )
    ]
    if not any(strategy.plugin is not None for strategy in kept):
        raise EmptySelection(
            f"plugins={sorted(wanted_plugins)} strategies={sorted(wanted_strategies)} select no "
            f"strategy that attacks anything. An empty probe set measures nothing while every "
            f"artifact downstream reports itself complete."
        )

    referenced = {strategy.plugin for strategy in kept if strategy.plugin is not None}
    return catalogue.model_copy(
        update={
            "strategies": kept,
            "plugins": [plugin for plugin in catalogue.plugins if plugin.id in referenced],
        }
    )


@dataclass(frozen=True)
class Checked:
    """A bundle that passed every check publishing runs, as publishing would write it."""

    needs_base: frozenset[str]
    """The grounding declaration, normalised."""

    delivered: dict[str, delivery_store.Delivery]
    """The delivery declaration, normalised, by strategy id."""

    @property
    def conducted(self) -> tuple[str, ...]:
        return tuple(sorted(self.delivered))


def check(
    catalogue: Catalogue,
    contract: ContractSpec,
    engines: Sequence[Any],
    transforms: Sequence[Any] = (),
    twisters: Sequence[Any] = (),
    *,
    needs_base: Mapping[str, Any] | Sequence[str] | None = None,
    delivery: Mapping[str, Any] | None = None,
) -> Checked:
    """Everything publishing checks, without writing: the six rejections against the bundle's own
    contract, the grounding declaration against the phrasings it describes, the delivery
    declaration against the strategies it names.

    What `POST /catalogues:validate` runs, so an author finds out before a version is taken.

    Raises:
        ValueError: As `publish` would, for the same bundle.
    """
    validate(catalogue, validation_contract(contract), engines, transforms, twisters)
    grounded = grounding_store.normalise(needs_base) if needs_base is not None else frozenset()
    _validate_grounding(grounded, catalogue)
    delivered = delivery_store.normalise(delivery) if delivery else {}
    _validate_delivery(delivered, catalogue)
    return Checked(needs_base=grounded, delivered=delivered)


def publish(
    store: ObjectStore,
    name: str,
    catalogue: Catalogue,
    contract: ContractSpec,
    engines: Sequence[Any],
    transforms: Sequence[Any] = (),
    twisters: Sequence[Any] = (),
    *,
    needs_base: Mapping[str, Any] | Sequence[str] | None = None,
    delivery: Mapping[str, Any] | None = None,
) -> Published:
    """Validate and write the next version of a bundle: catalogue, contract and sidecars.

    The six rejections run against the bundle's own contract before anything is written, so a
    refused bundle leaves the store exactly as it was -- and a plugin charging a principle the
    contract does not carry is refused here rather than discovered when nothing can grade it.

    The grounding sidecar is checked against the phrasing it describes (`_validate_grounding`); the
    delivery sidecar for naming only strategies the catalogue carries and no control
    (`_validate_delivery`); everything else about a delivery is refused by
    `redteam_store.delivery.normalise`, which is what keeps a model id from entering by this door.

    **The sidecars are written first.** Two writes cannot be one, and a publish that dies between
    them has to leave something the store can live with. A catalogue version with no contract beside
    it would not be that: nothing could ever add the contract to it, because the store only appends.
    A sidecar with no catalogue is: the listing ignores it, and the next publish completes it or
    steps over it (see `_next_version`).

    **Publishing what is already published writes nothing.** The newest version holding exactly this
    catalogue and exactly these sidecars is answered as it is, `created=False`. A collision on the
    write -- another publisher landed the version this one listed as free -- is answered by listing
    again and taking the next number, a bounded number of times, so two publishers of different
    bundles land as two versions and nobody's bytes disappear.

    Raises:
        ValueError: The catalogue fails one of the six rejections, the grounding declaration
            disagrees with a strategy's phrasing, or the delivery declaration is malformed, names a
            strategy the catalogue does not carry, or conducts a control.
        ObjectAlreadyExists: Every version this publish tried to claim was taken first.
    """
    checked = check(
        catalogue,
        contract,
        engines,
        transforms,
        twisters,
        needs_base=needs_base,
        delivery=delivery,
    )
    grounded, delivered = checked.needs_base, checked.delivered

    payload = _canonical(catalogue)
    contract_bytes = contract_store.encode(as_raw(contract))
    encoded: tuple[bytes | None, ...] = (
        contract_bytes,
        grounding_store.encode(grounded) if grounded else None,
        delivery_store.encode(delivered) if delivered else None,
    )
    conducted = tuple(sorted(delivered))

    def answer(version: int, *, created: bool) -> Published:
        return Published(
            name=name,
            version=version,
            key=layout.catalogue(name, version),
            digest=_digest(payload),
            contract_digest=_digest(contract_bytes),
            principles=len(contract.principles),
            created=created,
            delivered=conducted,
        )

    rejected: set[int] = set()
    for _ in range(CLAIM_ATTEMPTS):
        published = versions(store, name)
        if published and _already_holds(store, name, published[-1], payload, encoded):
            return answer(published[-1], created=False)
        claim = json.dumps(
            {
                "catalogue": _digest(payload),
                "sidecars": [_digest(part) if part is not None else None for part in encoded],
            },
            sort_keys=True,
        ).encode()
        version = _next_version(store, name, claim, rejected)
        # _next_version may observe a publication that completed after our first listing.
        published = versions(store, name)
        if published and _already_holds(store, name, published[-1], payload, encoded):
            return answer(published[-1], created=False)
        try:
            store.put(layout.catalogue_claim(name, version), claim, content_type="application/json")
        except ObjectAlreadyExists as taken:
            if store.get(layout.catalogue_claim(name, version)) != claim:
                collision = taken
                continue
        if (lost := _claim_sidecars(store, name, version, encoded)) is not None:
            # Somebody else's sidecar landed at this version between the listing and the write.
            # `_next_version` decides on the next round whether it carries what this publish holds.
            collision = lost
            rejected.add(version)
            continue
        if not _sidecars_hold(store, name, version, encoded):
            collision = ObjectAlreadyExists(layout.catalogue_claim(name, version))
            rejected.add(version)
            continue
        key = layout.catalogue(name, version)
        try:
            store.put(key, payload, content_type="application/json")
        except ObjectAlreadyExists as taken:
            if _already_holds(store, name, version, payload, encoded):
                # A twin of this publish completed the same version first -- the same catalogue
                # and the same sidecars. Same asset, same answer: nothing of ours is missing from
                # the store. The same catalogue under different sidecars is a different asset, and
                # takes the next version like any other collision.
                return answer(version, created=False)
            collision = taken
            continue
        return answer(version, created=True)
    raise collision


def _claim_sidecars(
    store: ObjectStore, name: str, version: int, encoded: tuple[bytes | None, ...]
) -> ObjectAlreadyExists | None:
    """Write every sidecar this publish declares at `version`. Returns the collision, if any.

    A key that already holds these exact bytes is left alone rather than rewritten -- that is
    `_next_version` having landed on the orphan this publish is completing.
    """
    for key, expected in _sidecars_at(name, version, encoded):
        try:
            store.put(key, expected, content_type="application/json")
        except ObjectAlreadyExists as taken:
            if store.get(key) != expected:
                return taken
    return None


def _sidecars_at(
    name: str, version: int, encoded: tuple[bytes | None, ...]
) -> tuple[tuple[str, bytes], ...]:
    """The sidecar keys this publish writes at `version`, with their bytes. Absent ones are
    absent."""
    return tuple(
        (spell(name, version), payload)
        for spell, payload in zip(_SIDECARS, encoded, strict=True)
        if payload is not None
    )


def _sidecars_hold(
    store: ObjectStore, name: str, version: int, encoded: tuple[bytes | None, ...]
) -> bool:
    """Whether `version` carries exactly these sidecars -- no more, no fewer, byte for byte.

    A sidecar this publish does not declare must be *absent* rather than ignored: the same
    catalogue published under two contracts is two different assets, and so is one with and without
    a grounding declaration or a delivery.
    """
    for spell, expected in zip(_SIDECARS, encoded, strict=True):
        key = spell(name, version)
        if expected is None:
            if store.exists(key):
                return False
        elif not store.exists(key) or store.get(key) != expected:
            return False
    return True


def _already_holds(
    store: ObjectStore,
    name: str,
    version: int,
    payload: bytes,
    encoded: tuple[bytes | None, ...],
) -> bool:
    """Whether `version` holds exactly this catalogue with exactly these sidecars."""
    if store.get(layout.catalogue(name, version)) != payload:
        return False
    return _sidecars_hold(store, name, version, encoded)


def _next_version(store: ObjectStore, name: str, claim: bytes, rejected: set[int]) -> int:
    """Resume an identical reserved bundle, skipping unclaimed legacy sidecar fragments."""
    published = versions(store, name)
    version = (published[-1] + 1) if published else FIRST_VERSION
    while True:
        if version in rejected:
            version += 1
            continue
        key = layout.catalogue_claim(name, version)
        if store.exists(key):
            if store.get(key) == claim:
                return version
        elif not any(store.exists(spell(name, version)) for spell in _SIDECARS):
            return version
        version += 1


def _validate_grounding(needs_base: frozenset[str], catalogue: Catalogue) -> None:
    """The grounding declaration, held against the catalogue it describes.

    **A declaration naming a strategy the catalogue does not carry** is a declaration about nothing.

    **A strategy whose phrasing leans on `{premise}` and is not declared** is refused by name. That
    strategy needs a base -- the slot is where the premise goes -- and a run that declares no brain
    would generate it anyway with the slot removed. The declaration is the catalogue's own statement
    of which strategies need a base, so it has to be complete.

    The reverse is allowed on purpose: a strategy declared as needing a base whose phrasing carries
    no slot is the case the sidecar exists for. gaussia appends the premise on that branch, and a
    catalogue that wants it has to be able to ask.
    """
    strategies = {strategy.id: strategy for strategy in catalogue.strategies}
    unknown = sorted(needs_base - set(strategies))
    if unknown:
        raise ValueError(
            f"the grounding declaration names strategies the catalogue does not carry: {unknown}"
        )
    undeclared = sorted(
        identifier
        for identifier, strategy in strategies.items()
        if _PREMISE_SLOT in strategy.phrasing_hint and identifier not in needs_base
    )
    if undeclared:
        raise GroundingMisdeclared(undeclared)


def _validate_delivery(
    deliveries: Mapping[str, delivery_store.Delivery], catalogue: Catalogue
) -> None:
    """The delivery declaration, held against the catalogue it describes.

    Every id has to exist, and a conducted delivery has to sit on a strategy that attacks something:
    an attacker is steered toward the plugin's objective, and a control has no plugin and no
    objective. A conducted control would be a conversation with nothing to aim at, and a control
    that is not the same question as the attack is not a control.
    """
    strategies = {strategy.id: strategy for strategy in catalogue.strategies}
    unknown = sorted(set(deliveries) - set(strategies))
    if unknown:
        raise DeliveryMisdeclared(unknown)
    controls = sorted(
        identifier
        for identifier, declared in deliveries.items()
        if declared.conducted and strategies[identifier].plugin is None
    )
    if controls:
        raise ValueError(
            f"the delivery sidecar conducts {controls} as conversations, and those strategies are "
            f"controls: with no plugin there is no objective to steer toward, and a control that "
            f"escalates is not the same question as the attack"
        )


def _canonical(catalogue: Catalogue) -> bytes:
    """Serialised the same way every time, so the digest names the content and not the
    formatting."""
    return json.dumps(
        catalogue.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def _digest(payload: bytes) -> str:
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"
