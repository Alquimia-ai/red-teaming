"""The S3-compatible backend. Serves MinIO, AWS and Ceph RGW with one implementation.

Append-only is enforced by the service, not hoped for. `put` is a conditional create -- `PutObject`
with `If-None-Match: *` -- so two writers of one key are decided by the bucket, atomically, and the
loser gets `ObjectAlreadyExists`. A `HEAD` followed by an unconditional `PUT` is not the same
thing: the gap between the two requests is exactly the window in which two publishers both see a
version as free, both write it, and one of them silently disappears.

**The guarantee is checked before it is relied on.** A backend that does not honour the header does
not refuse the write, it performs it, so a store that merely *sent* the header would be append-only
in name only. `verify()` proves the behaviour once per process and refuses to serve otherwise.
"""

from __future__ import annotations

from typing import Any

from redteam_store import layout
from redteam_store.interface import ObjectAlreadyExists, ObjectNotFound, StoreCannotClaim

PRECONDITION_FAILED = "PreconditionFailed"
"""What botocore reports when `If-None-Match: *` met an existing key. The one answer that proves the
write was refused rather than performed."""

NOT_IMPLEMENTED = "NotImplemented"
"""What a backend answers when it recognises the header and declines to honour it. Loud, and the
better of the two ways a backend can fail us -- the other is to ignore it and overwrite."""

_MISSING = ("404", "NoSuchKey")
_PROBE_BODY = b"conditional-write"


class S3ObjectStore:
    def __init__(
        self,
        bucket: str,
        *,
        endpoint_url: str | None = None,
        access_key: str | None = None,
        secret_key: str | None = None,
        region: str | None = None,
        client: Any | None = None,
    ) -> None:
        """Args:
        client: A ready boto3 S3 client, for a test that wants to script the bucket's answers.
            Built from the other arguments when absent; absent keys let boto3's default credential
            chain answer, which is how a pod with a workload identity authenticates.
        """
        self._bucket = bucket
        if client is None:
            import boto3

            client = boto3.client(
                "s3",
                endpoint_url=endpoint_url,
                aws_access_key_id=access_key,
                aws_secret_access_key=secret_key,
                region_name=region,
            )
        self._client: Any = client

    def put(self, key: str, data: bytes, *, content_type: str | None = None) -> None:
        """Create `key`, or raise `ObjectAlreadyExists`. One request, decided by the bucket."""
        from botocore.exceptions import ClientError

        extra = {"ContentType": content_type} if content_type else {}
        try:
            self._client.put_object(
                Bucket=self._bucket, Key=key, Body=data, IfNoneMatch="*", **extra
            )
        except ClientError as exc:
            code = _code(exc)
            if code == PRECONDITION_FAILED:
                raise ObjectAlreadyExists(key) from exc
            if code == NOT_IMPLEMENTED:
                raise StoreCannotClaim(self._bucket, code) from exc
            raise

    def verify(self) -> None:
        """Prove the bucket refuses a second write of one key, or refuse to serve.

        Two conditional writes of a probe key. The second must come back `PreconditionFailed`; if
        the bucket answers success it has ignored the header, and every "append-only" claim made on
        top of it -- a trace is evidence, a version means what it meant, one runner per run -- is
        false. On a bucket that has been verified before, the first write already collides, which
        is the same proof one request sooner.

        Raises:
            StoreCannotClaim: The bucket performed a write it should have refused, or declined the
                header outright.
        """
        try:
            self.put(layout.store_probe(), _PROBE_BODY)
        except ObjectAlreadyExists:
            return
        try:
            self.put(layout.store_probe(), _PROBE_BODY)
        except ObjectAlreadyExists:
            return
        raise StoreCannotClaim(self._bucket, "the second write of one key was performed")

    def get(self, key: str) -> bytes:
        from botocore.exceptions import ClientError

        try:
            response = self._client.get_object(Bucket=self._bucket, Key=key)
        except ClientError as exc:
            if _code(exc) in _MISSING:
                raise ObjectNotFound(key) from exc
            raise
        return bytes(response["Body"].read())

    def exists(self, key: str) -> bool:
        from botocore.exceptions import ClientError

        try:
            self._client.head_object(Bucket=self._bucket, Key=key)
        except ClientError as exc:
            if _code(exc) in _MISSING:
                return False
            raise
        return True

    def list_prefix(self, prefix: str) -> list[str]:
        """Every key under the prefix, sorted, paginating because a run has thousands of them."""
        keys: list[str] = []
        paginator = self._client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self._bucket, Prefix=prefix):
            keys.extend(item["Key"] for item in page.get("Contents", []))
        return sorted(keys)


def _code(exc: Any) -> str:
    """botocore's error code, by name. The service speaks in names, so the mapping does too."""
    return str(exc.response.get("Error", {}).get("Code", ""))
