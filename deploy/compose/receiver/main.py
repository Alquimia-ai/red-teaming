"""The local consumer: acknowledge a delivery only after keeping it, and answer what was kept.

What a real consumer does with a webhook is its own business; what every consumer should do is what
this one does -- persist first, acknowledge second, deduplicate on the idempotency key -- so a
delivery retried after a lost acknowledgement is stored once. It keeps deliveries in its own bucket
on the same MinIO the platform uses, under a key derived from the idempotency key, with a
conditional write so the second copy of a delivery is refused rather than overwritten.

`GET /received?run_id=` is what `redteam receiver export` reads.
"""

from __future__ import annotations

import hashlib
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

import boto3
from botocore.exceptions import ClientError

BUCKET = os.environ.get("REDTEAM_RECEIVER_BUCKET", "red-teaming-deliveries")
PREFIX = "deliveries/"


def storage() -> Any:
    return boto3.client(
        "s3",
        endpoint_url=os.environ["REDTEAM_S3_ENDPOINT"],
        aws_access_key_id=os.environ["REDTEAM_S3_ACCESS_KEY"],
        aws_secret_access_key=os.environ["REDTEAM_S3_SECRET_KEY"],
        region_name="us-east-1",
    )


def keep(payload: bytes, identity: str) -> None:
    """Write once; a second delivery under the same identity has to carry the same bytes."""
    client = storage()
    key = f"{PREFIX}{hashlib.sha256(identity.encode()).hexdigest()}.json"
    try:
        client.put_object(
            Bucket=BUCKET, Key=key, Body=payload, ContentType="application/json", IfNoneMatch="*"
        )
    except ClientError as collision:
        if collision.response["Error"]["Code"] not in ("PreconditionFailed", "412"):
            raise
        held = client.get_object(Bucket=BUCKET, Key=key)["Body"].read()
        if held != payload:
            raise ValueError("a different payload under the same delivery identity") from None


def received(run_id: str | None) -> list[dict[str, Any]]:
    client = storage()
    found = []
    for page in client.get_paginator("list_objects_v2").paginate(Bucket=BUCKET, Prefix=PREFIX):
        for obj in page.get("Contents", []):
            data = json.loads(client.get_object(Bucket=BUCKET, Key=obj["Key"])["Body"].read())
            if run_id is None or data.get("run_id") == run_id:
                found.append(data)
    return found


class Handler(BaseHTTPRequestHandler):
    def _json(self, status: int, body: Any) -> None:
        payload = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/healthz":
            self._json(200, {"status": "ok"})
            return
        if parsed.path == "/received":
            run_id = parse_qs(parsed.query).get("run_id", [None])[0]
            try:
                self._json(200, received(run_id))
            except Exception as failed:
                self._json(503, {"detail": f"persisted deliveries could not be read: {failed}"})
            return
        self._json(404, {"detail": "not found"})

    def do_POST(self) -> None:
        if urlparse(self.path).path not in ("/hook", "/webhook"):
            self._json(404, {"detail": "not found"})
            return
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length)
        try:
            body = json.loads(raw)
        except ValueError:
            self._json(400, {"detail": "the delivery is not JSON"})
            return
        identity = (
            self.headers.get("Idempotency-Key") or f"{body.get('run_id')}:{body.get('phase')}"
        )
        payload = json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
        try:
            keep(payload, identity)
        except ValueError as conflict:
            self._json(409, {"detail": str(conflict)})
            return
        except Exception as failed:
            self._json(503, {"detail": f"delivery was not persisted; retry: {failed}"})
            return
        self._json(200, {"status": "received"})

    def log_message(self, format: str, *args: Any) -> None:
        print(f"{self.command} {self.path}", flush=True)


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", 8080), Handler).serve_forever()
