"""The contract sidecar: the behavioural contract a catalogue's plugins charge, read from the store.

Every response the profiler and the exploiter collect is graded against the contract's principles,
so which contract graded a run is part of what that run measured. It lives beside the catalogue as
`contract.json`, published as part of the same version, because the plugins name its principles:
a catalogue and a contract revised apart would let a published catalogue charge a principle that no
longer exists, or grade a finished run against wording its author never saw.

Store logic only. Parsing is `redteam_contracts.contract`; binding a grader to the result needs
gaussia and lives in the catalogue package. This module reads bytes, hands back the parsed
declaration, and answers the one question a run with several catalogues has to ask: do they all
agree on what the assistant is held to.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from redteam_contracts.contract import ContractSpec, parse_contract_spec
from redteam_store import layout, versioned
from redteam_store.interface import ObjectNotFound, ObjectStore


class ContractMissing(KeyError):
    """A catalogue version with no contract sidecar.

    Not a default and not an empty contract: a catalogue whose plugins charge principles nobody
    declared cannot be graded, and publishing refuses it. Reaching this on a published version means
    a version that predates the sidecar or a store somebody edited by hand.
    """

    def __init__(self, name: str, version: int) -> None:
        super().__init__(f"catalogue {name!r} v{version} carries no contract sidecar")
        self.name = name
        self.version = version


class ContractMismatch(ValueError):
    """The catalogues one run selected carry different contracts.

    A run grades every exchange against one contract; two catalogues that disagree on the
    principles -- or on their weights, or on a rubric's wording -- cannot be graded together
    without somebody choosing, and that choice is not the platform's to make in silence. Refused
    at the gate, by name.
    """


def encode(raw: Any) -> bytes:
    """The canonical bytes of a contract: sorted keys, no whitespace. What passed validation is
    exactly what lands, and the digest means the content rather than the formatting."""
    return json.dumps(raw, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
        "utf-8"
    )


def load_bytes(store: ObjectStore, name: str, version: int) -> bytes:
    try:
        return store.get(layout.catalogue_contract(name, version))
    except ObjectNotFound as absent:
        raise ContractMissing(name, version) from absent


def load(store: ObjectStore, name: str, version: int) -> ContractSpec:
    """The contract one catalogue version carries, parsed."""
    return parse_contract_spec(load_bytes(store, name, version))


def digest(store: ObjectStore, name: str, version: int) -> str:
    """The digest of the sidecar's bytes, which is what two catalogues are compared by."""
    return versioned.digest(load_bytes(store, name, version))


def shared(store: ObjectStore, versions: Mapping[str, int]) -> tuple[ContractSpec, str]:
    """The one contract every catalogue a run froze carries, and its digest.

    Compared by digest of the canonical bytes, so two catalogues that published the same
    declaration -- whoever authored it and however it was formatted -- agree, and two that differ
    in a single weight do not.

    Raises:
        ValueError: No catalogues were named.
        ContractMissing: A named version carries no contract.
        ContractMismatch: Two named versions carry different contracts.
    """
    if not versions:
        raise ValueError("a run names at least one catalogue; none was given")
    digests: dict[str, str] = {}
    for name, version in versions.items():
        digests[f"{name} v{version}"] = digest(store, name, version)
    distinct = sorted(set(digests.values()))
    if len(distinct) > 1:
        by_digest = {
            d: sorted(label for label, found in digests.items() if found == d) for d in distinct
        }
        raise ContractMismatch(
            f"the selected catalogues carry {len(distinct)} different contracts: "
            + "; ".join(f"{labels} share {d[:19]}…" for d, labels in by_digest.items())
            + ". A run grades against one contract; publish the catalogues with the same one."
        )
    name, version = next(iter(versions.items()))
    return load(store, name, version), distinct[0]
