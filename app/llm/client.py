from __future__ import annotations

from typing import Any, Protocol, TypeVar

import httpx
from pydantic import BaseModel

from app.config import Settings
from app.llm.structured_output import parse_structured_output

SchemaT = TypeVar("SchemaT", bound=BaseModel)


class LlmClientError(RuntimeError):
    pass


class LlmTimeoutError(LlmClientError):
    pass


class StructuredOutputClient(Protocol):
    async def complete_structured(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        schema: type[SchemaT],
    ) -> SchemaT: ...


class OllamaLlmClient:
    def __init__(
        self,
        settings: Settings,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._model = settings.ollama_chat_model
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            base_url=str(settings.ollama_base_url).rstrip("/"),
            timeout=httpx.Timeout(settings.ollama_timeout_seconds),
        )

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def complete_structured(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        schema: type[SchemaT],
    ) -> SchemaT:
        payload: dict[str, Any] = {
            "model": self._model,
            "stream": False,
            "format": schema.model_json_schema(),
            "options": {"temperature": 0},
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }
        try:
            response = await self._client.post("/api/chat", json=payload)
            response.raise_for_status()
        except httpx.TimeoutException as error:
            raise LlmTimeoutError("Ollama classification timed out") from error
        except httpx.HTTPError as error:
            raise LlmClientError("Ollama classification request failed") from error

        try:
            body = response.json()
            content = body["message"]["content"]
        except (KeyError, TypeError, ValueError) as error:
            raise LlmClientError("Ollama returned an invalid chat response") from error
        if not isinstance(content, str):
            raise LlmClientError("Ollama returned non-text chat content")
        return parse_structured_output(content, schema)
