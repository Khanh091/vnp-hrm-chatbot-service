from typing import Any

from fastapi.testclient import TestClient

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
        self.preview_calls: list[str] = []
        self.routing_service = None

    async def process(
        self,
        message: str,
        trusted_context: TrustedExecutionContext,
    ) -> ChatPipelineResult:
        self.calls.append((message, trusted_context))
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
