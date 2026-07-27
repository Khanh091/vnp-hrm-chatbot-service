import json
import logging

import httpx
import pytest

from app.retrieval.embeddings import EmbeddingError, OllamaEmbeddingProvider
from tests.conftest import build_settings


@pytest.mark.asyncio
async def test_embedding_provider_batches_documents_and_reuses_client() -> None:
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        payload = json.loads(request.content)
        assert payload["input"] == ["one", "two"]
        return httpx.Response(
            200,
            json={"embeddings": [[0.1, 0.2], [0.3, 0.4]]},
        )

    settings = build_settings().model_copy(
        update={"tool_embedding_dimension": 2}
    )
    http_client = httpx.AsyncClient(
        base_url="http://ollama.test",
        transport=httpx.MockTransport(handler),
    )
    provider = OllamaEmbeddingProvider(settings, client=http_client)
    try:
        result = await provider.embed_documents(["one", "two"])
    finally:
        await http_client.aclose()

    assert result == [[0.1, 0.2], [0.3, 0.4]]
    assert calls == 1


@pytest.mark.asyncio
async def test_embedding_provider_validates_dimension() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"embeddings": [[0.1]]})

    http_client = httpx.AsyncClient(
        base_url="http://ollama.test",
        transport=httpx.MockTransport(handler),
    )
    provider = OllamaEmbeddingProvider(
        build_settings().model_copy(update={"tool_embedding_dimension": 2}),
        client=http_client,
    )
    try:
        with pytest.raises(EmbeddingError, match="dimension"):
            await provider.embed_query("test")
    finally:
        await http_client.aclose()


@pytest.mark.asyncio
async def test_embedding_failure_does_not_log_api_key(
    caplog: pytest.LogCaptureFixture,
) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    secret = "DO-NOT-LOG-THIS-KEY"
    settings = build_settings().model_copy(
        update={"odoo_internal_api_key": secret}
    )
    http_client = httpx.AsyncClient(
        base_url="http://ollama.test",
        transport=httpx.MockTransport(handler),
    )
    provider = OllamaEmbeddingProvider(settings, client=http_client)
    try:
        with caplog.at_level(logging.INFO), pytest.raises(EmbeddingError):
            await provider.embed_query("test")
    finally:
        await http_client.aclose()

    assert secret not in caplog.text
