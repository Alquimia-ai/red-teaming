"""The S3 backend's one promise -- create or refuse, in one request -- against a scripted bucket.

Nothing here reaches a network. The fake below answers the way botocore does, error codes by name,
so what is tested is the mapping and the discipline: no read before the write, the header on the
write, the refusal read back as `ObjectAlreadyExists`, and a bucket that ignores the header found
out before it is trusted.
"""

from __future__ import annotations

from typing import Any

import pytest
from botocore.exceptions import ClientError

from redteam_store import layout
from redteam_store.interface import ObjectAlreadyExists, ObjectNotFound, StoreCannotClaim
from redteam_store.s3 import S3ObjectStore


class _Bucket:
    """A bucket that honours `If-None-Match: *` the way S3, MinIO and Ceph RGW do."""

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.calls: list[tuple[str, str]] = []

    def put_object(self, *, Bucket: str, Key: str, Body: bytes, **extra: Any) -> dict[str, Any]:
        self.calls.append(("put_object", Key))
        if extra.get("IfNoneMatch") == "*" and Key in self.objects:
            raise _refused("PreconditionFailed", "PutObject")
        self.objects[Key] = Body
        return {}

    def head_object(self, *, Bucket: str, Key: str) -> dict[str, Any]:
        self.calls.append(("head_object", Key))
        if Key not in self.objects:
            raise _refused("404", "HeadObject")
        return {}

    def get_object(self, *, Bucket: str, Key: str) -> dict[str, Any]:
        self.calls.append(("get_object", Key))
        if Key not in self.objects:
            raise _refused("NoSuchKey", "GetObject")
        return {"Body": _Body(self.objects[Key])}


class _Overwriting(_Bucket):
    """A bucket that recognises nothing and performs every write. The backend to refuse."""

    def put_object(self, *, Bucket: str, Key: str, Body: bytes, **extra: Any) -> dict[str, Any]:
        self.calls.append(("put_object", Key))
        self.objects[Key] = Body
        return {}


class _Declining(_Bucket):
    """A bucket that recognises the header and says it does not implement it."""

    def put_object(self, *, Bucket: str, Key: str, Body: bytes, **extra: Any) -> dict[str, Any]:
        self.calls.append(("put_object", Key))
        if "IfNoneMatch" in extra:
            raise _refused("NotImplemented", "PutObject")
        self.objects[Key] = Body
        return {}


class _Body:
    def __init__(self, data: bytes) -> None:
        self._data = data

    def read(self) -> bytes:
        return self._data


def _refused(code: str, operation: str) -> ClientError:
    return ClientError({"Error": {"Code": code, "Message": code}}, operation)


def _store(bucket: _Bucket) -> S3ObjectStore:
    return S3ObjectStore("evidence", client=bucket)


def test_a_put_is_one_conditional_request_and_no_read() -> None:
    """The read-then-write it replaces was the race: two writers both saw the key as free."""
    bucket = _Bucket()
    _store(bucket).put("runs/r/spec.json", b"{}", content_type="application/json")

    assert bucket.calls == [("put_object", "runs/r/spec.json")]
    assert bucket.objects["runs/r/spec.json"] == b"{}"


def test_the_bucket_s_refusal_is_the_store_s_refusal() -> None:
    bucket = _Bucket()
    store = _store(bucket)
    store.put("k", b"first")

    with pytest.raises(ObjectAlreadyExists):
        store.put("k", b"second")
    assert bucket.objects["k"] == b"first"


def test_verify_passes_on_a_bucket_that_refuses_the_second_write() -> None:
    bucket = _Bucket()
    _store(bucket).verify()

    assert [key for _, key in bucket.calls] == [layout.store_probe(), layout.store_probe()]


def test_verify_on_an_already_verified_bucket_is_one_request() -> None:
    """The probe key from an earlier process already collides, which is the same proof sooner."""
    bucket = _Bucket()
    bucket.objects[layout.store_probe()] = b"conditional-write"

    _store(bucket).verify()

    assert len(bucket.calls) == 1


def test_a_bucket_that_performs_the_second_write_is_refused_before_it_is_trusted() -> None:
    """Sending the header is not the guarantee; the refusal is. A backend that ignores it would be
    append-only in name only, and every trace on it rewritable."""
    with pytest.raises(StoreCannotClaim, match="second write"):
        _store(_Overwriting()).verify()


def test_a_bucket_that_declines_the_header_is_refused_by_name() -> None:
    with pytest.raises(StoreCannotClaim, match="NotImplemented"):
        _store(_Declining()).verify()


def test_get_and_exists_read_the_bucket_as_before() -> None:
    bucket = _Bucket()
    store = _store(bucket)
    store.put("k", b"v")

    assert store.get("k") == b"v"
    assert store.exists("k") is True
    assert store.exists("missing") is False
    with pytest.raises(ObjectNotFound):
        store.get("missing")


def test_an_unrelated_error_is_not_swallowed() -> None:
    class _Broken(_Bucket):
        def put_object(self, **kwargs: Any) -> dict[str, Any]:
            raise _refused("AccessDenied", "PutObject")

    with pytest.raises(ClientError, match="AccessDenied"):
        _store(_Broken()).put("k", b"v")
