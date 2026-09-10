"""Embeddings over an OpenAI-compatible API, for the realism estimator.

gaussia's `EmbeddingRealismEstimator` takes an `Embedder` and ships two, both of which need torch.
Neither is installed and neither should be -- the runner is the image that starts once per run, and
pulling a deep learning runtime into it to embed a few hundred short strings is the wrong trade.
The embedding model arrives as configuration exactly as the judge's does, and the endpoint with it.

The request shape is the OpenAI one -- `{"model", "input": [...]}` in, `data[i].embedding` out --
which every hosted provider and every self-hosted server worth pointing at speaks, vLLM's
embeddings server included.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import httpx
import numpy as np
from gaussia.core.embedder import Embedder

if TYPE_CHECKING:
    from redteam_contracts.run_spec import ModelSpec

DEFAULT_TIMEOUT = 60.0
BATCH = 64
"""Inputs per request. Providers cap the batch and the cap varies; sixty-four sits under every one
seen and keeps a realism pool of a few hundred phrasings to a handful of calls."""


class EmbeddingFailed(RuntimeError):
    """The endpoint answered with something that is not a list of vectors, or did not answer."""


class OpenAICompatibleEmbedder(Embedder):  # type: ignore[misc]  # gaussia ships no stubs
    """Encode through an embeddings endpoint.

    Args:
        endpoint: The full embeddings URL. Explicit rather than a base to append to, because which
            path is exactly what differs between providers.
        model: The embedding model the endpoint serves. Configuration, never a constant here.
        api_key: The credential, already resolved by the caller. Absent for a server on the
            appliance's own network that authenticates nobody.
    """

    def __init__(
        self,
        endpoint: str,
        model: str,
        *,
        api_key: str | None = None,
        timeout: float = DEFAULT_TIMEOUT,
        client: httpx.Client | None = None,
    ) -> None:
        self._endpoint = endpoint
        self._model = model
        self._headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self._client = client or httpx.Client(timeout=timeout)

    @property
    def model(self) -> str:
        return self._model

    def encode(self, sentences: list[str]) -> np.ndarray:
        if not sentences:
            return np.zeros((0, 0), dtype=np.float32)
        vectors: list[list[float]] = []
        for start in range(0, len(sentences), BATCH):
            vectors.extend(self._batch(sentences[start : start + BATCH]))
        return np.asarray(vectors, dtype=np.float32)

    def _batch(self, inputs: list[str]) -> list[list[float]]:
        try:
            response = self._client.post(
                self._endpoint,
                json={"model": self._model, "input": inputs},
                headers=self._headers,
            )
            response.raise_for_status()
            body: dict[str, Any] = response.json()
            rows = sorted(body["data"], key=lambda item: int(item.get("index", 0)))
            vectors = [[float(x) for x in row["embedding"]] for row in rows]
        except Exception as error:
            raise EmbeddingFailed(f"{type(error).__name__}: {error}") from error
        if len(vectors) != len(inputs):
            raise EmbeddingFailed(f"asked for {len(inputs)} embeddings and received {len(vectors)}")
        return vectors


def embedder_for(spec: ModelSpec, api_key: str | None) -> OpenAICompatibleEmbedder:
    """The embedder a `ModelSpec` declares. The endpoint is required: there is no default place an
    embedding comes from, and naming one here would be a provider URL bound in code."""
    if not spec.endpoint:
        raise ValueError(
            f"the embedder {spec.model!r} needs an endpoint -- the embeddings URL the provider "
            f"serves it at. There is no default, on purpose."
        )
    return OpenAICompatibleEmbedder(spec.endpoint, spec.model, api_key=api_key)
