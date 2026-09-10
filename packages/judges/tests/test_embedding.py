"""Embeddings over an API: the request the provider expects, and the vectors in the order asked."""

from __future__ import annotations

import json

import httpx
import numpy as np
import pytest

from redteam_contracts.run_spec import ModelSpec
from redteam_judges.embedding import BATCH, EmbeddingFailed, OpenAICompatibleEmbedder, embedder_for


def _client(handler: object) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))  # type: ignore[arg-type]


def test_the_request_is_the_openai_shape_and_the_credential_is_a_bearer() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers.get("authorization")
        seen["body"] = json.loads(request.content)
        data = [{"index": 0, "embedding": [0.1, 0.2]}, {"index": 1, "embedding": [0.3, 0.4]}]
        return httpx.Response(200, json={"data": data})

    embedder = OpenAICompatibleEmbedder(
        "http://e/v1/embeddings", "vendor/embed", api_key="k", client=_client(handler)
    )
    vectors = embedder.encode(["a", "b"])

    assert seen["auth"] == "Bearer k"
    assert seen["body"] == {"model": "vendor/embed", "input": ["a", "b"]}
    assert vectors.shape == (2, 2)
    assert vectors.dtype == np.float32


def test_vectors_come_back_in_the_order_asked_whatever_the_provider_returns() -> None:
    """A provider is free to answer out of order; the realism estimator pairs vectors with
    sentences by position, so this is what makes the pairing right."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"data": [{"index": 1, "embedding": [1.0]}, {"index": 0, "embedding": [0.0]}]},
        )

    embedder = OpenAICompatibleEmbedder("http://e", "m", client=_client(handler))
    vectors = embedder.encode(["first", "second"])
    assert vectors.tolist() == [[0.0], [1.0]]


def test_a_large_pool_is_sent_in_batches() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        n = len(json.loads(request.content)["input"])
        data = [{"index": i, "embedding": [0.0]} for i in range(n)]
        return httpx.Response(200, json={"data": data})

    OpenAICompatibleEmbedder("http://e", "m", client=_client(handler)).encode(["x"] * (BATCH + 1))
    assert calls == 2


def test_a_short_answer_is_a_failure_not_a_shorter_pool() -> None:
    """Fewer vectors than sentences would silently shrink the prior the budget compares against."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": [{"index": 0, "embedding": [0.0]}]})

    with pytest.raises(EmbeddingFailed, match="asked for 2"):
        OpenAICompatibleEmbedder("http://e", "m", client=_client(handler)).encode(["a", "b"])


def test_the_endpoint_is_required_since_there_is_no_default_place_an_embedding_comes_from() -> None:
    with pytest.raises(ValueError, match="endpoint"):
        embedder_for(ModelSpec(model="vendor/embed", provider="openrouter"), api_key=None)
