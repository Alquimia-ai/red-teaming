"""An in-memory store. The tests' store, and the reference for what append-only means."""

from __future__ import annotations

import threading

from redteam_store.interface import ObjectAlreadyExists, ObjectNotFound


class MemoryObjectStore:
    """Append-only, and thread-safe because the runner writes traces concurrently.

    The lock is not decoration: without it two units closing at once can both see a key as free and
    both write it, which is precisely the overwrite the append-only rule exists to prevent.
    """

    def __init__(self) -> None:
        self._objects: dict[str, bytes] = {}
        self._lock = threading.Lock()

    def put(self, key: str, data: bytes, *, content_type: str | None = None) -> None:
        with self._lock:
            if key in self._objects:
                raise ObjectAlreadyExists(key)
            self._objects[key] = data

    def get(self, key: str) -> bytes:
        with self._lock:
            try:
                return self._objects[key]
            except KeyError:
                raise ObjectNotFound(key) from None

    def exists(self, key: str) -> bool:
        with self._lock:
            return key in self._objects

    def list_prefix(self, prefix: str) -> list[str]:
        with self._lock:
            return sorted(k for k in self._objects if k.startswith(prefix))
