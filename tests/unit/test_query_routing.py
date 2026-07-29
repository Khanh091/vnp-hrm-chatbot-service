import json
from typing import Any

import httpx
import pytest
from pydantic import SecretStr

from app.config import Settings
from app.llm.client import (
    GroqLlmClient,
    LlmTimeoutError,
    OllamaLlmClient,
    build_llm_client,
)
from app.llm.structured_output import StructuredOutputError
from app.routing.query_classifier import QueryClassifier, QueryClassifierError
from app.routing.query_normalizer import QueryNormalizer
from app.routing.rules import infer_rule_hints
from app.routing.schemas import (
    Domain,
    Operation,
    QueryClassification,
    RouteType,
    SubjectScope,
)


class FakeStructuredClient:
    def __init__(
        self,
        result: QueryClassification | Exception,
    ) -> None:
        self.result = result
        self.calls = 0
        self.last_user_prompt = ""

    async def complete_structured(self, **kwargs: Any) -> QueryClassification:
        self.calls += 1
        self.last_user_prompt = kwargs["user_prompt"]
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


@pytest.mark.parametrize(
    ("query", "route", "domain"),
    [
        (
            "Tôi còn bao nhiêu ngày phép?",
            RouteType.STRUCTURED_QUERY,
            Domain.LEAVE,
        ),
        (
            "Tạo đơn nghỉ ngày mai",
            RouteType.TRANSACTION,
            Domain.LEAVE,
        ),
        (
            "Email công việc của tôi",
            RouteType.STRUCTURED_QUERY,
            Domain.PROFILE,
        ),
        (
            "Tháng này tôi đi muộn mấy lần?",
            RouteType.STRUCTURED_QUERY,
            Domain.ATTENDANCE,
        ),
        (
            "Thời tiết hôm nay?",
            RouteType.UNSUPPORTED,
            Domain.GENERAL,
        ),
    ],
)
@pytest.mark.asyncio
async def test_classifier_returns_valid_structured_categories(
    query: str,
    route: RouteType,
    domain: Domain,
) -> None:
    expected = QueryClassification(
        route_type=route,
        primary_domain=domain,
        confidence=0.9,
    )
    client = FakeStructuredClient(expected)

    result = await QueryClassifier(client).classify(
        QueryNormalizer().normalize(query)
    )

    assert result == expected
    assert client.calls == 1
    assert query in client.last_user_prompt


@pytest.mark.asyncio
async def test_classifier_supports_multi_domain() -> None:
    expected = QueryClassification(
        route_type=RouteType.ANALYTICS,
        primary_domain=Domain.ATTENDANCE,
        secondary_domains=[Domain.LEAVE],
        capability_hint="missing_work",
        operation_hint=Operation.EXPLAIN,
        scope=SubjectScope.SELF,
        confidence=0.91,
        reason_code="ATTENDANCE_MISSING_WORK_REQUIRES_LEAVE_CONTEXT",
    )

    result = await QueryClassifier(FakeStructuredClient(expected)).classify(
        QueryNormalizer().normalize(
            "Tôi nghỉ hôm qua nên bảng công bị thiếu đúng không?"
        )
    )

    assert result.secondary_domains == [Domain.LEAVE]
    assert result.operation_hint is Operation.EXPLAIN


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error",
    [
        StructuredOutputError("bad schema"),
        LlmTimeoutError("timeout"),
    ],
    ids=["invalid-structured-output", "llm-timeout"],
)
async def test_classifier_wraps_llm_failures(error: Exception) -> None:
    with pytest.raises(QueryClassifierError):
        await QueryClassifier(FakeStructuredClient(error)).classify(
            QueryNormalizer().normalize("Tôi còn bao nhiêu ngày phép?")
        )


@pytest.mark.asyncio
async def test_explicit_write_cannot_be_downgraded_to_query() -> None:
    unsafe = QueryClassification(
        route_type=RouteType.STRUCTURED_QUERY,
        primary_domain=Domain.LEAVE,
        operation_hint=Operation.GET,
        confidence=0.8,
    )

    with pytest.raises(QueryClassifierError, match="contradicted"):
        await QueryClassifier(FakeStructuredClient(unsafe)).classify(
            QueryNormalizer().normalize("Tạo đơn nghỉ phép ngày mai")
        )


def test_query_normalizer_preserves_vietnamese_and_original() -> None:
    result = QueryNormalizer().normalize(
        "  Tôi   còn bao nhiêu \n ngày phép?  "
    )

    assert result.original_text == "  Tôi   còn bao nhiêu \n ngày phép?  "
    assert result.normalized_text == "Tôi còn bao nhiêu ngày phép?"


def test_rule_layer_only_hints_explicit_write() -> None:
    hints = infer_rule_hints("Tạo đơn nghỉ phép ngày mai")
    read_hints = infer_rule_hints("Tôi còn bao nhiêu ngày phép?")

    assert hints.route_hint is RouteType.TRANSACTION
    assert hints.domain_hint is Domain.LEAVE
    assert hints.operation_hint is Operation.CREATE
    assert read_hints.route_hint is None


def test_rule_layer_does_not_treat_read_question_as_registration() -> None:
    hints = infer_rule_hints(
        "Có những loại nghỉ nào tôi được đăng ký?"
    )

    assert hints.route_hint is None
    assert hints.operation_hint is None


@pytest.mark.asyncio
async def test_ollama_classifier_disables_thinking() -> None:
    captured_payload: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured_payload.update(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "message": {
                    "content": QueryClassification(
                        route_type=RouteType.STRUCTURED_QUERY,
                        primary_domain=Domain.LEAVE,
                        confidence=0.95,
                    ).model_dump_json()
                }
            },
        )

    http_client = httpx.AsyncClient(
        base_url="http://ollama.test",
        transport=httpx.MockTransport(handler),
    )
    settings = Settings.model_construct(
        ollama_chat_model="test-classifier",
        ollama_base_url="http://ollama.test",
        ollama_timeout_seconds=10.0,
    )
    client = OllamaLlmClient(settings, client=http_client)

    try:
        await client.complete_structured(
            system_prompt="system",
            user_prompt="user",
            schema=QueryClassification,
        )
    finally:
        await http_client.aclose()

    assert captured_payload["think"] is False
    assert captured_payload["options"]["temperature"] == 0
    assert set(captured_payload["format"]["required"]) == set(
        captured_payload["format"]["properties"]
    )


@pytest.mark.asyncio
async def test_groq_client_uses_json_mode_without_reasoning() -> None:
    captured_payload: dict[str, Any] = {}
    captured_authorization = ""

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal captured_authorization
        captured_payload.update(json.loads(request.content))
        captured_authorization = request.headers["Authorization"]
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": QueryClassification(
                                route_type=RouteType.STRUCTURED_QUERY,
                                primary_domain=Domain.LEAVE,
                                confidence=0.96,
                            ).model_dump_json()
                        }
                    }
                ]
            },
        )

    http_client = httpx.AsyncClient(
        base_url="https://groq.test/openai/v1",
        transport=httpx.MockTransport(handler),
    )
    settings = Settings.model_construct(
        llm_provider="groq",
        groq_base_url="https://groq.test/openai/v1",
        groq_api_key=SecretStr("unit-test-secret"),
        groq_chat_model="qwen/qwen3.6-27b",
        groq_timeout_seconds=10.0,
    )
    client = GroqLlmClient(settings, client=http_client)
    try:
        result = await client.complete_structured(
            system_prompt="system",
            user_prompt="user",
            schema=QueryClassification,
        )
    finally:
        await http_client.aclose()

    assert result.primary_domain is Domain.LEAVE
    assert captured_payload["reasoning_effort"] == "none"
    assert captured_payload["response_format"] == {"type": "json_object"}
    assert "JSON Schema" in captured_payload["messages"][0]["content"]
    assert captured_authorization == "Bearer unit-test-secret"
    built_client = build_llm_client(settings)
    assert isinstance(built_client, GroqLlmClient)
    await built_client.close()


@pytest.mark.asyncio
async def test_groq_compound_omits_qwen_only_reasoning_effort() -> None:
    captured_payload: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured_payload.update(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": QueryClassification(
                                route_type=RouteType.STRUCTURED_QUERY,
                                primary_domain=Domain.PROFILE,
                                capability_hint="contact",
                                confidence=0.99,
                                reason_code="PROFILE_CONTACT",
                            ).model_dump_json()
                        }
                    }
                ]
            },
        )

    http_client = httpx.AsyncClient(
        base_url="https://groq.test/openai/v1",
        transport=httpx.MockTransport(handler),
    )
    settings = Settings.model_construct(
        llm_provider="groq",
        groq_base_url="https://groq.test/openai/v1",
        groq_api_key=SecretStr("unit-test-secret"),
        groq_chat_model="groq/compound",
        groq_timeout_seconds=10.0,
    )
    client = GroqLlmClient(settings, client=http_client)
    try:
        await client.complete_structured(
            system_prompt="system",
            user_prompt="Email của tôi là gì?",
            schema=QueryClassification,
        )
    finally:
        await http_client.aclose()

    assert captured_payload["model"] == "groq/compound"
    assert "reasoning_effort" not in captured_payload
    assert captured_payload["tool_choice"] == "none"
    assert captured_payload["response_format"] == {"type": "json_object"}


@pytest.mark.asyncio
async def test_groq_gpt_oss_uses_low_reasoning_effort() -> None:
    captured_payload: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured_payload.update(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": QueryClassification(
                                route_type=RouteType.STRUCTURED_QUERY,
                                primary_domain=Domain.PROFILE,
                                confidence=0.9,
                            ).model_dump_json()
                        }
                    }
                ]
            },
        )

    http_client = httpx.AsyncClient(
        base_url="https://groq.test/openai/v1",
        transport=httpx.MockTransport(handler),
    )
    settings = Settings.model_construct(
        llm_provider="groq",
        groq_base_url="https://groq.test/openai/v1",
        groq_api_key=SecretStr("unit-test-secret"),
        groq_chat_model="openai/gpt-oss-20b",
        groq_timeout_seconds=10.0,
    )
    client = GroqLlmClient(settings, client=http_client)
    try:
        await client.complete_structured(
            system_prompt="system",
            user_prompt="Email của tôi là gì?",
            schema=QueryClassification,
        )
    finally:
        await http_client.aclose()

    assert captured_payload["reasoning_effort"] == "low"


@pytest.mark.asyncio
async def test_llm_factory_selects_classifier_and_response_models() -> None:
    settings = Settings.model_construct(
        llm_provider="groq",
        groq_base_url="https://groq.test/openai/v1",
        groq_api_key=SecretStr("unit-test-secret"),
        groq_chat_model="legacy-model",
        groq_classifier_model="llama-3.1-8b-instant",
        groq_selector_model="qwen/qwen3.6-27b",
        groq_response_model="openai/gpt-oss-20b",
        groq_timeout_seconds=10.0,
    )
    classifier = build_llm_client(settings, purpose="classifier")
    selector = build_llm_client(settings, purpose="selector")
    response = build_llm_client(settings, purpose="response")
    try:
        assert isinstance(classifier, GroqLlmClient)
        assert isinstance(selector, GroqLlmClient)
        assert isinstance(response, GroqLlmClient)
        assert classifier.model == "llama-3.1-8b-instant"
        assert selector.model == "qwen/qwen3.6-27b"
        assert response.model == "openai/gpt-oss-20b"
    finally:
        await classifier.close()
        await selector.close()
        await response.close()
