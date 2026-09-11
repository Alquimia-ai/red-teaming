"""How each artifact is encoded, and why each format was chosen.

| Artifact | Format | Why |
|---|---|---|
| Traces | JSONL + zstd | Written incrementally, read as a stream, and gaining a field on a
conversation forces no schema change |
| Spec, probes, dataset, profile, report, manifest | JSON | Small, read whole, and meant to be
legible to a person auditing |
"""

from __future__ import annotations

import json
from collections.abc import Iterable

import zstandard

from redteam_contracts.trace import Trace


def encode_trace(trace: Trace) -> bytes:
    """One JSON object per turn, compressed.

    Line-per-turn rather than one object for the conversation, because that is what makes the format
    appendable: a turn can be written as it closes without rewriting what came before.
    """
    lines = [json.dumps({"_meta": _trace_meta(trace)}, separators=(",", ":"))]
    lines += [json.dumps(t.model_dump(mode="json"), separators=(",", ":")) for t in trace.turns]
    payload = ("\n".join(lines) + "\n").encode()
    return zstandard.ZstdCompressor(level=10).compress(payload)


def decode_trace(data: bytes) -> Trace:
    text = zstandard.ZstdDecompressor().decompress(data).decode()
    records = [json.loads(line) for line in text.splitlines() if line]
    meta = records[0]["_meta"]
    return Trace(turns=tuple(records[1:]), **meta)


def _trace_meta(trace: Trace) -> dict[str, object]:
    payload: dict[str, object] = dict(trace.model_dump(mode="json"))
    payload.pop("turns")
    return payload


def encode_json(payload: object) -> bytes:
    return json.dumps(payload, indent=2, sort_keys=True, default=str).encode()


def decode_jsonl(data: bytes) -> Iterable[dict[str, object]]:
    text = zstandard.ZstdDecompressor().decompress(data).decode()
    for line in text.splitlines():
        if line:
            yield json.loads(line)
