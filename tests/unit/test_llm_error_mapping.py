from typing import Any

import httpx
import pytest
from pydantic import SecretStr

from app.config import Settings
from app.llm.client import GroqLlmClient
from app.llm.exceptions import (
    LlmAuthenticationError,
    LlmBadRequestError,
    LlmPermissionError,
    LlmProviderError,
    LlmRateLimitError,
    LlmStructuredOutputError,
    LlmTimeoutError,
)
from app.routing.schemas import QueryClassification


def settings() -> Settings:
    return Settings.model_construct(
        groq_base_url="https://groq.test/openai/v1",
        groq_api_key=SecretStr("unit-test-secret"),
        groq_chat_model="qwen/qwen3.6-27b",
        groq_timeout_seconds=1,
        groq_temperature=0.1,
        groq_reasoning_effort="none",
        llm_max_retries=0,
        llm_max_retry_after_seconds=3,
        llm_structured_repair_attempts=0,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (400, LlmBadRequestError),
        (401, LlmAuthenticationError),
        (403, LlmPermissionError),
        (408, LlmTimeoutError),
        (429, LlmRateLimitError),
        (500, LlmProviderError),
    ],
)
async def test_groq_http_status_maps_to_typed_exception(
    status: int,
    expected: type[Exception],
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status,
            headers={"Retry-After": "2"} if status == 429 else {},
            json={"error": {"type": "test_error", "code": "TEST_CODE"}},
        )

    http_client = httpx.AsyncClient(
        base_url="https://groq.test/openai/v1",
        transport=httpx.MockTransport(handler),
    )
    client = GroqLlmClient(settings(), client=http_client)
    try:
        with pytest.raises(expected):
            await client.complete_structured(
                system_prompt="system",
                user_prompt="user",
                schema=QueryClassification,
                operation="query_classification",
                request_id="req-test",
            )
    finally:
        await http_client.aclose()


@pytest.mark.asyncio
async def test_invalid_json_is_structured_output_not_rate_limit() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "not-json"}}]},
        )

    http_client = httpx.AsyncClient(
        base_url="https://groq.test/openai/v1",
        transport=httpx.MockTransport(handler),
    )
    client = GroqLlmClient(settings(), client=http_client)
    try:
        with pytest.raises(LlmStructuredOutputError):
            await client.complete_structured(
                system_prompt="system",
                user_prompt="user",
                schema=QueryClassification,
            )
    finally:
        await http_client.aclose()


@pytest.mark.asyncio
async def test_timeout_maps_to_timeout_error() -> None:
    def handler(request: httpx.Request) -> Any:
        raise httpx.ReadTimeout("timed out", request=request)

    http_client = httpx.AsyncClient(
        base_url="https://groq.test/openai/v1",
        transport=httpx.MockTransport(handler),
    )
    client = GroqLlmClient(settings(), client=http_client)
    try:
        with pytest.raises(LlmTimeoutError):
            await client.complete_structured(
                system_prompt="system",
                user_prompt="user",
                schema=QueryClassification,
            )
    finally:
        await http_client.aclose()
