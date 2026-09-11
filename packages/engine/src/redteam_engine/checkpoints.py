"""Atomic recovery records; deliverable files are verified projections of these records."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from redteam_engine.dataset import RoastDataset
from redteam_store.codec import encode_json
from redteam_store.interface import ObjectAlreadyExists, ObjectStore


class RecoveryIncomplete(RuntimeError):
    """Evidence cannot establish safe recovery. Preserve it and use a new run id."""

    kind = "recovery_incomplete"


class Checkpoint(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal[1] = 1
    components: dict[str, str] = Field(min_length=1)
    sessions: list[RoastDataset]


def put_same(store: ObjectStore, key: str, payload: bytes) -> None:
    """An idempotent write means identical content, never ignoring a conflict."""
    try:
        store.put(key, payload, content_type="application/json")
    except ObjectAlreadyExists:
        if store.get(key) != payload:
            raise RecoveryIncomplete(f"conflicting evidence at {key}; start a new run") from None


def save(store: ObjectStore, key: str, record: Checkpoint) -> None:
    put_same(store, key, encode_json(record.model_dump(mode="json")))


def read(store: ObjectStore, key: str) -> Checkpoint:
    try:
        return Checkpoint.model_validate_json(store.get(key))
    except ValueError as invalid:
        raise RecoveryIncomplete(f"invalid checkpoint at {key}; start a new run") from invalid
