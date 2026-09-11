"""Publish the business data a run needs into an empty store, through the API, once.

Nothing loads these from a file at run time: catalogue bundles and priors are read from the object
store at the version a run froze. That leaves somebody having to put them there the first time,
and this is that somebody. Publishing an identical bundle again writes nothing, so a stack brought
up twice seeds once, and a bundle that changed on disk becomes the next version -- which is exactly
what "somebody changed this" means.

Standard library only, so it runs from a bare Python image and from a checkout alike:

    python deploy/seed/seed.py                          # against http://localhost:8080
    REDTEAM_API_URL=http://api:8080 python deploy/seed/seed.py
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

HERE = Path(os.environ.get("REDTEAM_SEED_DIR") or Path(__file__).resolve().parent)
API = os.environ.get("REDTEAM_API_URL", "http://localhost:8080").rstrip("/")
WAIT_SECONDS = 120


def request(method: str, path: str, body: dict[str, Any] | None = None) -> tuple[int, Any]:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        f"{API}{path}", data=data, method=method, headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as response:
            return response.status, json.loads(response.read() or b"null")
    except urllib.error.HTTPError as refused:
        return refused.code, json.loads(refused.read() or b"null")


def wait_for_api() -> None:
    deadline = time.monotonic() + WAIT_SECONDS
    while time.monotonic() < deadline:
        try:
            status, _ = request("GET", "/healthz")
            if status == 200:
                return
        except (urllib.error.URLError, OSError):
            pass
        time.sleep(2)
    print(f"the API at {API} never answered /healthz", file=sys.stderr)
    sys.exit(1)


def bundle(directory: Path) -> dict[str, Any]:
    body: dict[str, Any] = {
        "name": directory.name,
        "catalogue": json.loads((directory / "catalogue.json").read_text()),
        "contract": json.loads((directory / "contract.json").read_text()),
    }
    grounding = directory / "grounding.json"
    if grounding.is_file():
        body["needs_base"] = json.loads(grounding.read_text())["needs_base"]
    delivery = directory / "delivery.json"
    if delivery.is_file():
        body["delivery"] = json.loads(delivery.read_text())
    return body


def main() -> int:
    wait_for_api()
    print(f"seeding {API} from {HERE}")
    failed = 0
    for directory in sorted((HERE / "catalogues").iterdir()):
        if not (directory / "catalogue.json").is_file():
            continue
        status, answer = request("POST", "/catalogues", bundle(directory))
        if status in (200, 201):
            verb = "published" if answer.get("created") else "already published"
            print(f"  catalogue {directory.name}: {verb} as version {answer['version']}")
        else:
            failed += 1
            print(f"  catalogue {directory.name}: refused {status}: {answer}", file=sys.stderr)
    for directory in sorted((HERE / "priors").iterdir()):
        prior = directory / "prior.json"
        if not prior.is_file():
            continue
        status, answer = request(
            "POST",
            "/priors",
            {"name": directory.name, "phrasings": json.loads(prior.read_text())},
        )
        if status in (200, 201):
            verb = "published" if answer.get("created") else "already published"
            print(f"  prior {directory.name}: {verb} as version {answer['version']}")
        else:
            failed += 1
            print(f"  prior {directory.name}: refused {status}: {answer}", file=sys.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
