from __future__ import annotations

import math
from typing import Protocol

import httpx

from app.config import Settings


class EmbeddingError(RuntimeError):
    pass


class EmbeddingProvider(Protocol):
    @property
    def dimension(self) -> int: ...

    async def embed_query(self, text: str) -> list[float]: ...

    async def embed_documents(
        self,
        texts: list[str],
    ) -> list[list[float]]: ...


class OllamaEmbeddingProvider:
    """Async batched embeddings using one reusable Ollama HTTP client."""

    def __init__(
        self,
        settings: Settings,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._model = settings.ollama_embedding_model
        self._dimension = settings.tool_embedding_dimension
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            base_url=str(settings.ollama_base_url).rstrip("/"),
            timeout=httpx.Timeout(settings.ollama_timeout_seconds),
        )

    @property
    def dimension(self) -> int:
        return self._dimension

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def embed_query(self, text: str) -> list[float]:
        embeddings = await self._embed([text])
        return embeddings[0]

    async def embed_documents(
        self,
        texts: list[str],
    ) -> list[list[float]]:
        if not texts:
            return []
        return await self._embed(texts)

    async def _embed(self, texts: list[str]) -> list[list[float]]:
        try:
            response = await self._client.post(
                "/api/embed",
                json={"model": self._model, "input": texts},
            )
            response.raise_for_status()
            raw_embeddings = response.json()["embeddings"]
        except httpx.TimeoutException as error:
            raise EmbeddingError("Ollama embedding request timed out") from error
        except (httpx.HTTPError, KeyError, TypeError, ValueError) as error:
            raise EmbeddingError("Ollama embedding request failed") from error

        if not isinstance(raw_embeddings, list) or len(raw_embeddings) != len(texts):
            raise EmbeddingError("Ollama returned an invalid embedding batch")

        embeddings: list[list[float]] = []
        for raw_embedding in raw_embeddings:
            if not isinstance(raw_embedding, list):
                raise EmbeddingError("Ollama returned an invalid embedding")
            embedding = [float(value) for value in raw_embedding]
            if len(embedding) != self._dimension:
                raise EmbeddingError(
                    f"Embedding dimension must be {self._dimension}"
                )
            if not all(math.isfinite(value) for value in embedding):
                raise EmbeddingError("Embedding contains a non-finite value")
            embeddings.append(embedding)
        return embeddings
