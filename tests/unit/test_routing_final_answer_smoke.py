from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime, timezone
from typing import Any

import pytest

from app.answers import (
    AnswerContextBuilder,
    DeterministicAnswerFallback,
    FinalAnswerService,
    ToolResultSanitizer,
)
from app.api.routers.chat import _stream_events
from app.api.schemas.chat import ChatRequest
from app.context.dialog_manager import DialogTurnManager
from app.context.workflow_state import clear_active_workflow
from app.llm.exceptions import LlmRateLimitError
from app.orchestration.nodes.common import emit_graph_event
from app.orchestration.state import (
    ChatPipelineResult,
    ChatResponseType,
    ChatStageTimings,
    TurnType,
)
from app.persistence.models.conversation import Conversation
from app.routing.candidate_retriever import CandidateRetriever
from app.routing.schemas import (
    CandidateRetrievalRequest,
    Domain,
    QueryClassification,
)
from app.routing.taxonomy import Intent, Operation, QueryRoute, SubjectScope
from app.tools import build_tool_registry
from app.tools.definitions import ToolExecutionResult, TrustedExecutionContext


class NeverUsedEmbeddings:
    calls = 0

    async def embed_query(self, text: str) -> list[float]:
        self.calls += 1
        raise AssertionError(text)

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        raise AssertionError(texts)


class NeverUsedStore:
    async def has_candidates(self, **kwargs: Any) -> bool:
        raise AssertionError(kwargs)

    async def search(self, **kwargs: Any) -> list[Any]:
        raise AssertionError(kwargs)


class ChunkClient:
    def __init__(
        self,
        chunks: list[str],
        error: Exception | None = None,
    ) -> None:
        self.chunks = chunks
        self.error = error

    async def stream_text(self, **kwargs: Any) -> AsyncIterator[str]:
        del kwargs
        if self.error:
            raise self.error
        for chunk in self.chunks:
            yield chunk


def classification(intent: Intent, domain: Domain) -> QueryClassification:
    return QueryClassification(
        route=QueryRoute.DATA_QUERY,
        domain=domain,
        intent=intent,
        operation=Operation.READ,
        scope=SubjectScope.SELF,
        confidence=0.98,
        reason_code="SMOKE_TEST",
    )


def answer_context(
    intent: Intent,
    query: str,
    data: object,
    tool_name: str,
):
    builder = AnswerContextBuilder(
        ToolResultSanitizer(max_items=20, max_chars=12000)
    )
    return builder.build(
        original_query=query,
        classification=classification(intent, Domain.PROFILE),
        tool_name=tool_name,
        tool_result=ToolExecutionResult(
            tool_name=tool_name,
            success=True,
            data=data,
            latency_ms=1,
        ),
        locale="vi_VN",
        timezone="Asia/Ho_Chi_Minh",
    )


@pytest.mark.asyncio
async def test_late_count_maps_directly_without_embedding_or_selector() -> None:
    embeddings = NeverUsedEmbeddings()
    outcome = await CandidateRetriever(
        build_tool_registry(),
        embeddings,
        NeverUsedStore(),  # type: ignore[arg-type]
    ).retrieve(
        CandidateRetrievalRequest(
            query="số ngày đi muộn của tôi",
            classification=classification(
                Intent.ATTENDANCE_LATE_COUNT,
                Domain.ATTENDANCE,
            ),
            top_k=5,
            fetch_k=20,
            min_score=0.45,
        )
    )
    assert [item.tool_name for item in outcome.candidates] == [
        "attendance_get_monthly_summary"
    ]
    assert embeddings.calls == 0
    assert outcome.candidates[0].operation is Operation.READ


def test_sticky_leave_slot_accepts_dates_but_overrides_new_intents() -> None:
    manager = DialogTurnManager()
    assert manager.detect(
        message="30/7/2026",
        structured_clarification=None,
        expected_field="date_from",
    ) is TurnType.CLARIFICATION_ANSWER
    for query in ("lịch sử chấm công", "số ngày phép còn lại"):
        assert manager.detect(
            message=query,
            structured_clarification=None,
            expected_field="date_from",
        ) is TurnType.NEW_QUERY_OVERRIDE


@pytest.mark.asyncio
async def test_manager_answer_only_mentions_manager() -> None:
    context = answer_context(
        Intent.PROFILE_MANAGER,
        "cấp trên của tôi",
        {
            "job_title": {"name": "Bán hàng"},
            "department": {"name": "BĐT Sơn La"},
            "manager": None,
        },
        "profile_get_employment",
    )
    service = FinalAnswerService(
        ChunkClient(
            ["Hệ thống chưa lưu thông tin ", "quản lý trực tiếp của bạn."]
        ),
        DeterministicAnswerFallback(),
        temperature=0.1,
        max_tokens=300,
    )
    answer = "".join(
        [chunk async for chunk in service.stream_answer(context, request_id="r")]
    )
    assert answer == (
        "Hệ thống chưa lưu thông tin quản lý trực tiếp của bạn."
    )
    assert "phòng ban" not in answer.lower()


def test_contract_expiry_fallback_only_answers_expiry() -> None:
    context = answer_context(
        Intent.PROFILE_CONTRACT_EXPIRY,
        "hợp đồng bao giờ hết hạn",
        {
            "current_contract": {
                "contract_type": "Hợp đồng Cộng tác viên",
                "date_end": None,
                "state": "Hiệu lực",
            }
        },
        "profile_get_contracts",
    )
    answer = DeterministicAnswerFallback().format(context)
    assert answer == (
        "Hợp đồng hiện tại của bạn không có ngày kết thúc "
        "được lưu trên hệ thống."
    )


@pytest.mark.asyncio
async def test_education_answer_is_not_generic_success() -> None:
    context = answer_context(
        Intent.PROFILE_EDUCATION,
        "trình độ học vấn của tôi",
        {
            "records": [
                {
                    "education_level": "Đại học",
                    "major": "Công nghệ thông tin",
                }
            ]
        },
        "profile_get_education",
    )
    service = FinalAnswerService(
        ChunkClient(
            [
                "Trình độ học vấn đang được lưu của bạn là ",
                "Đại học, chuyên ngành Công nghệ thông tin.",
            ]
        ),
        DeterministicAnswerFallback(),
        temperature=0.1,
        max_tokens=300,
    )
    answer = "".join(
        [chunk async for chunk in service.stream_answer(context, request_id="r")]
    )
    assert "Đại học" in answer
    assert answer != "Đã truy xuất dữ liệu HRM thành công."


@pytest.mark.asyncio
async def test_final_answer_removes_markdown_bold_across_chunks() -> None:
    context = answer_context(
        Intent.PROFILE_DEPARTMENT,
        "tên phòng ban của tôi",
        {"department": {"name": "BĐT Sơn La"}},
        "profile_get_employment",
    )
    service = FinalAnswerService(
        ChunkClient(["Phòng ban của bạn là: *", "*BĐT Sơn La**."]),
        DeterministicAnswerFallback(),
        temperature=0.1,
        max_tokens=300,
    )
    answer = "".join(
        [chunk async for chunk in service.stream_answer(context, request_id="r")]
    )
    assert answer == "Phòng ban của bạn là: BĐT Sơn La."
    assert "*" not in answer


@pytest.mark.asyncio
async def test_sse_streams_answer_chunks_in_order() -> None:
    class Pipeline:
        async def process(self, *_: Any, **__: Any) -> ChatPipelineResult:
            emit_graph_event("answer_start", {"message_id": "m1"})
            for delta in ("Hợp đồng ", "hiện tại ", "chưa có ngày hết hạn."):
                emit_graph_event(
                    "answer_delta",
                    {"message_id": "m1", "delta": delta},
                )
            emit_graph_event(
                "answer_done",
                {
                    "message_id": "m1",
                    "answer": "Hợp đồng hiện tại chưa có ngày hết hạn.",
                },
            )
            return ChatPipelineResult(
                conversation_id="conv",
                type=ChatResponseType.ANSWER,
                answer="Hợp đồng hiện tại chưa có ngày hết hạn.",
                timings=ChatStageTimings(),
            )

    trusted = TrustedExecutionContext(
        odoo_user_id=1,
        timezone="Asia/Ho_Chi_Minh",
        conversation_id="conv",
        request_id="req",
    )
    chunks = [
        chunk
        async for chunk in _stream_events(
            Pipeline(),
            ChatRequest(message="hợp đồng bao giờ hết hạn"),
            trusted,
        )
    ]
    events = [
        line.removeprefix("event: ")
        for chunk in chunks
        for line in chunk.splitlines()
        if line.startswith("event: answer") or line == "event: done"
    ]
    assert events == [
        "answer_start",
        "answer_delta",
        "answer_delta",
        "answer_delta",
        "answer_done",
        "done",
    ]


@pytest.mark.asyncio
async def test_final_llm_rate_limit_keeps_tool_result_via_fallback() -> None:
    context = answer_context(
        Intent.PROFILE_MANAGER,
        "cấp trên của tôi",
        {"manager": None},
        "profile_get_employment",
    )
    service = FinalAnswerService(
        ChunkClient(
            [],
            LlmRateLimitError(
                "limited",
                http_status=429,
                retry_after_seconds=10,
            ),
        ),
        DeterministicAnswerFallback(),
        temperature=0.1,
        max_tokens=300,
    )
    answer = "".join(
        [chunk async for chunk in service.stream_answer(context, request_id="r")]
    )
    assert answer == (
        "Hệ thống chưa lưu thông tin quản lý trực tiếp của bạn."
    )


def test_workflow_cleanup_after_write_success_removes_sticky_state() -> None:
    conversation = Conversation(
        conversation_id="conv",
        odoo_user_id=1,
        status="completed",
        active_workflow="leave_create_request",
        pending_tool_name="leave_create_request",
        collected_arguments={"date_from": "2026-07-30"},
        missing_arguments=["date_to"],
        ambiguous_arguments=["date_from"],
        workflow_data={"current_field": "date_from"},
        last_message_at=datetime.now(timezone.utc),
        expires_at=datetime.now(timezone.utc),
    )
    values = clear_active_workflow(conversation)
    assert conversation.pending_tool_name is None
    assert conversation.missing_arguments == []
    assert values["workflow_data"] == {}
