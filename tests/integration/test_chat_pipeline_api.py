import asyncio
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.api.routers import chat as chat_router
from app.api.schemas.chat import ChatRequest
from app.main import create_app
from app.orchestration.state import (
    ChatPipelineResult,
    ChatResponseType,
    ChatStageTimings,
)
from app.tools.definitions import TrustedExecutionContext
from tests.conftest import StubOdooClient, build_settings


class FakePipeline:
    def __init__(self) -> None:
        self.calls: list[tuple[str, TrustedExecutionContext]] = []
        self.call_options: list[dict[str, Any]] = []
        self.preview_calls: list[str] = []
        self.routing_service = None

    async def process(
        self,
        message: str | None,
        trusted_context: TrustedExecutionContext,
        *,
        action_type: str | None = None,
        action_id: str | None = None,
        clarification: dict[str, Any] | None = None,
    ) -> ChatPipelineResult:
        self.calls.append((message, trusted_context))
        self.call_options.append(
            {
                "action_type": action_type,
                "action_id": action_id,
                "clarification": clarification,
            }
        )
        return ChatPipelineResult(
            conversation_id=trusted_context.conversation_id,
            type=ChatResponseType.ANSWER,
            answer="Bạn còn 12 ngày phép năm.",
            data={
                "tool_name": "leave_get_balance",
                "result": {"remaining_days": 12},
            },
            timings=ChatStageTimings(total_ms=3),
        )

    async def preview(self, message: str) -> dict[str, Any]:
        self.preview_calls.append(message)
        return {
            "classification": {},
            "candidates": [],
            "selection": None,
            "validation": None,
            "execution_skipped": True,
        }


class SlowPipeline(FakePipeline):
    async def process(
        self,
        message: str | None,
        trusted_context: TrustedExecutionContext,
        *,
        action_type: str | None = None,
        action_id: str | None = None,
        clarification: dict[str, Any] | None = None,
    ) -> ChatPipelineResult:
        await asyncio.sleep(0.03)
        return await super().process(
            message,
            trusted_context,
            action_type=action_type,
            action_id=action_id,
            clarification=clarification,
        )


def test_chat_builds_trusted_context_and_calls_pipeline() -> None:
    settings = build_settings()
    pipeline = FakePipeline()
    odoo = StubOdooClient(settings)
    with TestClient(
        create_app(
            settings=settings,
            odoo_client=odoo,
            chat_pipeline=pipeline,  # type: ignore[arg-type]
        )
    ) as client:
            response = client.post(
                "/api/v1/chat",
                headers={
                    "X-Request-ID": "req-chat-1",
                    "X-HRM-Chatbot-Ingress-Key": "test-ingress",
                    "X-Odoo-User-Id": "42",
                },
                json={
                    "message": "Tôi còn bao nhiêu ngày phép?",
                    "conversation_id": "conv-1",
                },
            )

    assert response.status_code == 200
    assert response.json()["type"] == "answer"
    _, trusted = pipeline.calls[0]
    assert trusted.odoo_user_id == 42
    assert trusted.employee_id == 10
    assert trusted.request_id == "req-chat-1"


def test_debug_tool_selection_never_executes() -> None:
    settings = build_settings().model_copy(update={"app_debug": True})
    pipeline = FakePipeline()
    with TestClient(
        create_app(
            settings=settings,
            odoo_client=StubOdooClient(settings),
            chat_pipeline=pipeline,  # type: ignore[arg-type]
        )
    ) as client:
        response = client.post(
            "/api/v1/debug/tool-selection",
            json={
                "message": "Hủy đơn nghỉ số 12",
                "execute": True,
            },
        )

    assert response.status_code == 200
    assert response.json()["execution_skipped"] is True
    assert pipeline.calls == []
    assert pipeline.preview_calls == ["Hủy đơn nghỉ số 12"]


def test_structured_clarification_is_forwarded() -> None:
    settings = build_settings()
    pipeline = FakePipeline()
    with TestClient(
        create_app(
            settings=settings,
            odoo_client=StubOdooClient(settings),
            chat_pipeline=pipeline,  # type: ignore[arg-type]
        )
    ) as client:
        response = client.post(
            "/api/v1/chat",
            headers={
                "X-HRM-Chatbot-Ingress-Key": "test-ingress",
                "X-Odoo-User-Id": "42",
            },
            json={
                "conversation_id": "conv-clarification",
                "clarification": {
                    "field": "leave_type_id",
                    "value": 5,
                    "label": "Phép năm",
                },
            },
        )

    assert response.status_code == 200
    assert pipeline.calls[0][0] == "Phép năm"
    assert pipeline.call_options[0]["clarification"] == {
        "field": "leave_type_id",
        "value": 5,
        "label": "Phép năm",
    }


def test_chat_stream_emits_connected_answer_and_done() -> None:
    settings = build_settings()
    pipeline = FakePipeline()
    with TestClient(
        create_app(
            settings=settings,
            odoo_client=StubOdooClient(settings),
            chat_pipeline=pipeline,  # type: ignore[arg-type]
        )
    ) as client:
        response = client.post(
            "/api/v1/chat/stream",
            headers={
                "X-HRM-Chatbot-Ingress-Key": "test-ingress",
                "X-Odoo-User-Id": "42",
            },
            json={"message": "Tôi còn bao nhiêu ngày phép?"},
        )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "event: status" in response.text
    assert '"type": "connected"' in response.text
    assert "event: answer" in response.text
    assert "event: done" in response.text


@pytest.mark.asyncio
async def test_chat_stream_heartbeat_does_not_cancel_pipeline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(chat_router, "_SSE_HEARTBEAT_SECONDS", 0.005)
    pipeline = SlowPipeline()
    trusted = TrustedExecutionContext(
        odoo_user_id=42,
        employee_id=10,
        company_id=1,
        timezone="Asia/Ho_Chi_Minh",
        language="vi_VN",
        conversation_id="conv-slow-stream",
        request_id="req-slow-stream",
    )

    chunks = [
        chunk
        async for chunk in chat_router._stream_events(
            pipeline,
            ChatRequest(message="Email của tôi là gì?"),
            trusted,
        )
    ]

    assert ": keep-alive\n\n" in chunks
    assert any(chunk.startswith("event: answer") for chunk in chunks)
    assert any(chunk.startswith("event: done") for chunk in chunks)
    assert len(pipeline.calls) == 1
