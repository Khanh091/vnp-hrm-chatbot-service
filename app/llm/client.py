from __future__ import annotations

import json
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


class LlmRateLimitError(LlmClientError):
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
        self._keep_alive = settings.ollama_keep_alive
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
        response_schema = schema.model_json_schema()
        response_schema["required"] = list(
            response_schema.get("properties", {})
        )
        payload: dict[str, Any] = {
            "model": self._model,
            "stream": False,
            "think": False,
            "keep_alive": self._keep_alive,
            "format": response_schema,
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


class GroqLlmClient:
    def __init__(
        self,
        settings: Settings,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        if settings.groq_api_key is None:
            raise ValueError("GROQ_API_KEY is required")
        self._model = settings.groq_chat_model
        self._authorization = (
            "Bearer " + settings.groq_api_key.get_secret_value()
        )
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            base_url=str(settings.groq_base_url).rstrip("/"),
            headers={"Content-Type": "application/json"},
            timeout=httpx.Timeout(settings.groq_timeout_seconds),
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
        response_schema = schema.model_json_schema()
        response_schema["required"] = list(
            response_schema.get("properties", {})
        )
        payload: dict[str, Any] = {
            "model": self._model,
            "temperature": 0.1,
            "max_completion_tokens": 1024,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        system_prompt
                        + "\n\nJSON Schema bắt buộc:\n"
                        + json.dumps(response_schema, ensure_ascii=False)
                    ),
                },
                {"role": "user", "content": user_prompt},
            ],
            "response_format": {"type": "json_object"},
        }
        if self._model.startswith("qwen/"):
            payload["reasoning_effort"] = "none"
        if self._model.startswith("groq/compound"):
            # Classification and tool selection never need Groq's web/code
            # tools; disabling them prevents data egress and extra latency.
            payload["tool_choice"] = "none"
        try:
            response = await self._client.post(
                "/chat/completions",
                json=payload,
                headers={"Authorization": self._authorization},
            )
            response.raise_for_status()
        except httpx.TimeoutException as error:
            raise LlmTimeoutError("Groq structured request timed out") from error
        except httpx.HTTPStatusError as error:
            if error.response.status_code == 429:
                raise LlmRateLimitError(
                    "Groq rate limit exceeded"
                ) from error
            raise LlmClientError("Groq structured request failed") from error
        except httpx.HTTPError as error:
            raise LlmClientError("Groq structured request failed") from error

        try:
            body = response.json()
            content = body["choices"][0]["message"]["content"]
        except (IndexError, KeyError, TypeError, ValueError) as error:
            raise LlmClientError("Groq returned an invalid chat response") from error
        if not isinstance(content, str):
            raise LlmClientError("Groq returned non-text chat content")
        return parse_structured_output(content, schema)


def build_llm_client(
    settings: Settings,
) -> OllamaLlmClient | GroqLlmClient:
    if settings.llm_provider == "groq":
        return GroqLlmClient(settings)
    return OllamaLlmClient(settings)
