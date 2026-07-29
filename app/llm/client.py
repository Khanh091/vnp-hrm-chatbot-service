from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from time import perf_counter
from typing import Any, Literal, Protocol, TypeVar

import httpx
from pydantic import BaseModel

from app.config import Settings
from app.llm.exceptions import (
    LlmAuthenticationError,
    LlmBadRequestError,
    LlmConnectionError,
    LlmPermissionError,
    LlmProviderError,
    LlmRateLimitError,
    LlmStructuredOutputError,
    LlmTimeoutError,
)
from app.llm.exceptions import (
    LlmClientError as BaseLlmClientError,
)
from app.llm.structured_output import parse_structured_output

SchemaT = TypeVar("SchemaT", bound=BaseModel)
logger = logging.getLogger(__name__)
LlmClientError = BaseLlmClientError


class StructuredOutputClient(Protocol):
    async def complete_structured(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        schema: type[SchemaT],
        operation: str = "structured_completion",
        request_id: str | None = None,
    ) -> SchemaT: ...


class TextStreamingClient(Protocol):
    def stream_text(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int,
        temperature: float,
        operation: str = "text_stream",
        request_id: str | None = None,
    ) -> AsyncIterator[str]: ...


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
        operation: str = "structured_completion",
        request_id: str | None = None,
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
            raise LlmTimeoutError("Ollama structured request timed out") from error
        except httpx.HTTPError as error:
            raise LlmConnectionError("Ollama structured request failed") from error

        try:
            body = response.json()
            content = body["message"]["content"]
        except (KeyError, TypeError, ValueError) as error:
            raise LlmStructuredOutputError(
                "Ollama returned an invalid chat response"
            ) from error
        if not isinstance(content, str):
            raise LlmStructuredOutputError(
                "Ollama returned non-text chat content"
            )
        return parse_structured_output(content, schema)

    async def stream_text(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int,
        temperature: float,
        operation: str = "text_stream",
        request_id: str | None = None,
    ) -> AsyncIterator[str]:
        del operation, request_id
        payload = {
            "model": self._model,
            "stream": True,
            "think": False,
            "keep_alive": self._keep_alive,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
            },
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }
        try:
            async with self._client.stream(
                "POST",
                "/api/chat",
                json=payload,
            ) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line:
                        continue
                    try:
                        body = json.loads(line)
                        content = body.get("message", {}).get("content")
                    except (TypeError, ValueError) as error:
                        raise LlmStructuredOutputError(
                            "Ollama returned an invalid text stream"
                        ) from error
                    if isinstance(content, str) and content:
                        yield content
        except httpx.TimeoutException as error:
            raise LlmTimeoutError("Ollama text stream timed out") from error
        except httpx.HTTPStatusError as error:
            raise LlmProviderError(
                "Ollama text stream request failed",
                http_status=error.response.status_code,
            ) from error
        except httpx.HTTPError as error:
            raise LlmConnectionError(
                "Ollama text stream connection failed"
            ) from error


class GroqLlmClient:
    def __init__(
        self,
        settings: Settings,
        *,
        model: str | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        if settings.groq_api_key is None:
            raise ValueError("GROQ_API_KEY is required")
        self._model = model or settings.groq_chat_model
        self._temperature = settings.groq_temperature
        self._reasoning_effort = settings.groq_reasoning_effort
        self._max_retries = settings.llm_max_retries
        self._max_retry_after = settings.llm_max_retry_after_seconds
        self._repair_attempts = settings.llm_structured_repair_attempts
        self._authorization = (
            "Bearer " + settings.groq_api_key.get_secret_value()
        )
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            base_url=str(settings.groq_base_url).rstrip("/"),
            headers={"Content-Type": "application/json"},
            timeout=httpx.Timeout(settings.groq_timeout_seconds),
        )

    @property
    def model(self) -> str:
        return self._model

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def complete_structured(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        schema: type[SchemaT],
        operation: str = "structured_completion",
        request_id: str | None = None,
    ) -> SchemaT:
        response_schema = schema.model_json_schema()
        response_schema["required"] = list(
            response_schema.get("properties", {})
        )
        payload: dict[str, Any] = {
            "model": self._model,
            "temperature": self._temperature,
            "max_completion_tokens": 1024,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        system_prompt
                        + "\n\nJSON Schema bắt buộc:\n"
                        + json.dumps(
                            response_schema,
                            ensure_ascii=False,
                            separators=(",", ":"),
                        )
                    ),
                },
                {"role": "user", "content": user_prompt},
            ],
            "response_format": {"type": "json_object"},
        }
        if self._model.startswith("qwen/"):
            payload["reasoning_effort"] = self._reasoning_effort
        elif self._model.startswith("openai/gpt-oss-"):
            payload["reasoning_effort"] = "low"
        if "compound" in self._model.lower():
            payload["tool_choice"] = "none"
        started = perf_counter()
        response: httpx.Response | None = None
        try:
            response = await self._request_with_retry(payload)
            body = response.json()
            message = body["choices"][0]["message"]
            if message.get("refusal"):
                raise LlmStructuredOutputError("Groq refused structured output")
            content = message["content"]
            if not isinstance(content, str):
                raise LlmStructuredOutputError(
                    "Groq returned non-text chat content"
                )
            try:
                return parse_structured_output(content, schema)
            except LlmStructuredOutputError:
                if self._repair_attempts == 0:
                    raise
                repair_payload = dict(payload)
                repair_payload["messages"] = [
                    *payload["messages"],
                    {
                        "role": "assistant",
                        "content": content[:2000],
                    },
                    {
                        "role": "user",
                        "content": "Sửa JSON trên để khớp schema. Chỉ trả JSON.",
                    },
                ]
                repaired = await self._request_with_retry(
                    repair_payload,
                    allow_retry=False,
                )
                repaired_body = repaired.json()
                repaired_content = repaired_body["choices"][0]["message"][
                    "content"
                ]
                if not isinstance(repaired_content, str):
                    raise LlmStructuredOutputError(
                        "Groq repair returned non-text content"
                    ) from None
                return parse_structured_output(repaired_content, schema)
        except (
            LlmClientError,
            IndexError,
            KeyError,
            TypeError,
            ValueError,
        ) as error:
            mapped = (
                error
                if isinstance(error, LlmClientError)
                else LlmStructuredOutputError(
                    "Groq returned an invalid chat response"
                )
            )
            self._log_failure(
                mapped,
                operation=operation,
                request_id=request_id,
                latency_ms=(perf_counter() - started) * 1000,
            )
            if mapped is error:
                raise mapped from error.__cause__
            raise mapped from error

    async def stream_text(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int,
        temperature: float,
        operation: str = "text_stream",
        request_id: str | None = None,
    ) -> AsyncIterator[str]:
        payload: dict[str, Any] = {
            "model": self._model,
            "temperature": temperature,
            "max_completion_tokens": max_tokens,
            "stream": True,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }
        if self._model.startswith("qwen/"):
            payload["reasoning_effort"] = self._reasoning_effort
        started = perf_counter()
        try:
            async with self._client.stream(
                "POST",
                "/chat/completions",
                json=payload,
                headers={"Authorization": self._authorization},
            ) as response:
                if not response.is_success:
                    await response.aread()
                    raise self._map_http_error(response)
                async for line in response.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    raw = line[5:].strip()
                    if raw == "[DONE]":
                        break
                    try:
                        body = json.loads(raw)
                        content = body["choices"][0]["delta"].get("content")
                    except (IndexError, KeyError, TypeError, ValueError) as error:
                        raise LlmStructuredOutputError(
                            "Groq returned an invalid text stream"
                        ) from error
                    if isinstance(content, str) and content:
                        yield content
        except httpx.TimeoutException as error:
            timeout_error = LlmTimeoutError("Groq text stream timed out")
            self._log_failure(
                timeout_error,
                operation=operation,
                request_id=request_id,
                latency_ms=(perf_counter() - started) * 1000,
            )
            raise timeout_error from error
        except httpx.HTTPError as error:
            connection_error = LlmConnectionError(
                "Groq text stream connection failed"
            )
            self._log_failure(
                connection_error,
                operation=operation,
                request_id=request_id,
                latency_ms=(perf_counter() - started) * 1000,
            )
            raise connection_error from error
        except LlmClientError as error:
            self._log_failure(
                error,
                operation=operation,
                request_id=request_id,
                latency_ms=(perf_counter() - started) * 1000,
            )
            raise

    async def _request_with_retry(
        self,
        payload: dict[str, Any],
        *,
        allow_retry: bool = True,
    ) -> httpx.Response:
        attempts = 0
        while True:
            try:
                response = await self._client.post(
                    "/chat/completions",
                    json=payload,
                    headers={"Authorization": self._authorization},
                )
            except httpx.TimeoutException as error:
                raise LlmTimeoutError(
                    "Groq structured request timed out"
                ) from error
            except httpx.HTTPError as error:
                raise LlmConnectionError(
                    "Groq structured connection failed"
                ) from error
            if response.is_success:
                return response
            mapped = self._map_http_error(response)
            retry_delay = self._retry_delay(mapped, attempts)
            if (
                not allow_retry
                or attempts >= self._max_retries
                or retry_delay is None
            ):
                raise mapped
            attempts += 1
            if retry_delay:
                await asyncio.sleep(retry_delay)

    def _retry_delay(
        self,
        error: LlmClientError,
        attempts: int,
    ) -> float | None:
        if attempts >= self._max_retries:
            return None
        if isinstance(error, LlmRateLimitError):
            delay = error.retry_after_seconds
            if delay is None or delay > self._max_retry_after:
                return None
            return delay
        if isinstance(error, LlmProviderError) and error.http_status in {
            502,
            503,
            504,
        }:
            return 0.2
        return None

    @staticmethod
    def _map_http_error(response: httpx.Response) -> LlmClientError:
        status = response.status_code
        code: str | None = None
        try:
            error_payload = response.json().get("error", {})
            if isinstance(error_payload, dict):
                raw_code = error_payload.get("code") or error_payload.get("type")
                code = str(raw_code)[:80] if raw_code is not None else None
        except (TypeError, ValueError):
            pass
        retry_after: float | None = None
        raw_retry_after = response.headers.get("Retry-After")
        if raw_retry_after:
            try:
                retry_after = max(0.0, float(raw_retry_after))
            except ValueError:
                retry_after = None
        if status == 400:
            return LlmBadRequestError(
                "Groq rejected the request",
                http_status=status,
                provider_error_code=code,
                retry_after_seconds=retry_after,
            )
        if status == 401:
            return LlmAuthenticationError(
                "Groq authentication failed",
                http_status=status,
                provider_error_code=code,
                retry_after_seconds=retry_after,
            )
        if status == 403:
            return LlmPermissionError(
                "Groq permission denied",
                http_status=status,
                provider_error_code=code,
                retry_after_seconds=retry_after,
            )
        if status == 408:
            return LlmTimeoutError(
                "Groq request timed out",
                http_status=status,
                provider_error_code=code,
                retry_after_seconds=retry_after,
            )
        if status == 429:
            return LlmRateLimitError(
                "Groq rate limit exceeded",
                http_status=status,
                provider_error_code=code,
                retry_after_seconds=retry_after,
            )
        return LlmProviderError(
            "Groq provider request failed",
            http_status=status,
            provider_error_code=code,
            retry_after_seconds=retry_after,
        )

    def _log_failure(
        self,
        error: LlmClientError,
        *,
        operation: str,
        request_id: str | None,
        latency_ms: float,
    ) -> None:
        logger.warning(
            "llm_request_failed provider=groq model=%s operation=%s "
            "http_status=%s provider_error_type=%s provider_error_code=%s "
            "retry_after_seconds=%s request_id=%s latency_ms=%.2f",
            self._model,
            operation,
            error.http_status,
            type(error).__name__,
            error.provider_error_code,
            error.retry_after_seconds,
            request_id,
            latency_ms,
        )


def build_llm_client(
    settings: Settings,
    *,
    purpose: Literal[
        "classifier",
        "selector",
        "response",
        "final_answer",
    ] = "classifier",
) -> OllamaLlmClient | GroqLlmClient:
    if settings.llm_provider == "groq":
        model = {
            "classifier": settings.groq_classifier_model,
            "selector": settings.groq_selector_model,
            "response": settings.groq_response_model,
            "final_answer": (
                settings.groq_final_answer_model
                or settings.groq_response_model
            ),
        }[purpose]
        return GroqLlmClient(
            settings,
            model=model or settings.groq_chat_model,
        )
    return OllamaLlmClient(settings)
