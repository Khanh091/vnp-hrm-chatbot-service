from typing import Any

import pytest

from app.context.conversation import ConversationStore
from app.orchestration.pipeline import ChatPipeline
from app.orchestration.state import ChatResponseType
from app.routing.argument_resolver import ArgumentResolver
from app.routing.schemas import (
    Domain,
    Operation,
    QueryClassification,
    RouteType,
    RoutingDebugResult,
    RoutingStageTimings,
    ToolCandidate,
    ToolSelection,
)
from app.routing.tool_selector import ToolSelector
from app.routing.validator import ToolSelectionValidator
from app.tools import build_tool_registry
from app.tools.definitions import ToolExecutionResult, TrustedExecutionContext
from app.tools.response_formatter import ToolResponseFormatter
from tests.conftest import build_settings


class FakeRouting:
    def __init__(
        self,
        *,
        route: RouteType,
        domain: Domain,
        tool_name: str | None,
    ) -> None:
        self.route_type = route
        self.domain = domain
        self.tool_name = tool_name

    async def route(self, message: str) -> RoutingDebugResult:
        candidates = []
        if self.tool_name is not None:
            tool = build_tool_registry().get(self.tool_name)
            candidates.append(
                ToolCandidate(
                    tool_name=tool.name,
                    domain=Domain(tool.domain.value),
                    capability=tool.capability,
                    operation=Operation(tool.operation.value),
                    score=0.93,
                    rank=1,
                )
            )
        return RoutingDebugResult(
            normalized_query=message.strip(),
            classification=QueryClassification(
                route_type=self.route_type,
                primary_domain=self.domain,
                operation_hint=(
                    candidates[0].operation if candidates else None
                ),
                confidence=0.95,
            ),
            candidates=candidates,
            timings=RoutingStageTimings(
                normalization_ms=0.1,
                classification_ms=1,
                embedding_ms=1,
                vector_search_ms=1,
            ),
        )


class FakeSelectorClient:
    def __init__(self, selection: ToolSelection) -> None:
        self.selection = selection
        self.calls = 0

    async def complete_structured(self, **kwargs: Any) -> ToolSelection:
        self.calls += 1
        return self.selection


class FakeExecutor:
    def __init__(self) -> None:
        self.calls = 0

    async def execute_validated(self, execution: Any) -> ToolExecutionResult:
        self.calls += 1
        return ToolExecutionResult(
            tool_name=execution.tool_name,
            success=True,
            data={
                "remaining_days": 12,
                "leave_type_name": "phép năm",
            },
            latency_ms=1,
        )


def pipeline(
    routing: FakeRouting,
    selection: ToolSelection,
    executor: FakeExecutor,
) -> ChatPipeline:
    registry = build_tool_registry()
    settings = build_settings()
    return ChatPipeline(
        routing,  # type: ignore[arg-type]
        ToolSelector(
            FakeSelectorClient(selection),  # type: ignore[arg-type]
            registry,
        ),
        ArgumentResolver(),
        ToolSelectionValidator(registry, settings),
        executor,  # type: ignore[arg-type]
        ToolResponseFormatter(),
        ConversationStore(settings.pending_action_ttl_seconds),
        registry,
    )


def trusted() -> TrustedExecutionContext:
    return TrustedExecutionContext(
        odoo_user_id=42,
        employee_id=10,
        company_id=1,
        timezone="Asia/Ho_Chi_Minh",
        language="vi_VN",
        conversation_id="conv-1",
        request_id="req-1",
    )


@pytest.mark.asyncio
async def test_read_query_executes_once_and_formats_grounded_answer() -> None:
    executor = FakeExecutor()
    service = pipeline(
        FakeRouting(
            route=RouteType.STRUCTURED_QUERY,
            domain=Domain.LEAVE,
            tool_name="leave_get_balance",
        ),
        ToolSelection(
            selected_tool="leave_get_balance",
            confidence=0.97,
            extracted_arguments={"year": 2026},
            reason_code="LEAVE_BALANCE",
        ),
        executor,
    )

    result = await service.process("Tôi còn bao nhiêu ngày phép?", trusted())

    assert result.type is ChatResponseType.ANSWER
    assert result.answer == "Bạn còn 12 ngày phép năm."
    assert executor.calls == 1


@pytest.mark.asyncio
async def test_missing_arguments_returns_clarification_without_execution() -> None:
    executor = FakeExecutor()
    service = pipeline(
        FakeRouting(
            route=RouteType.TRANSACTION,
            domain=Domain.LEAVE,
            tool_name="leave_create_request",
        ),
        ToolSelection(
            selected_tool="leave_create_request",
            confidence=0.95,
            missing_arguments=["date_from", "date_to", "leave_type_id"],
            requires_clarification=True,
            clarification_question="Bạn muốn bắt đầu nghỉ từ ngày nào?",
            reason_code="MISSING_DATE",
        ),
        executor,
    )

    result = await service.process("Tạo đơn nghỉ phép", trusted())

    assert result.type is ChatResponseType.CLARIFICATION_REQUIRED
    assert executor.calls == 0


@pytest.mark.asyncio
async def test_write_returns_pending_confirmation_without_execution() -> None:
    executor = FakeExecutor()
    service = pipeline(
        FakeRouting(
            route=RouteType.TRANSACTION,
            domain=Domain.LEAVE,
            tool_name="leave_cancel_request",
        ),
        ToolSelection(
            selected_tool="leave_cancel_request",
            confidence=0.96,
            extracted_arguments={"request_id": 12},
            reason_code="CANCEL_LEAVE",
        ),
        executor,
    )

    result = await service.process("Hủy đơn nghỉ số 12", trusted())

    assert result.type is ChatResponseType.CONFIRMATION_REQUIRED
    assert result.data is not None
    assert result.data["action_id"].startswith("act-")
    assert "idempotency_key" not in result.data["summary"]
    assert executor.calls == 0


@pytest.mark.asyncio
async def test_unsupported_and_empty_candidates_skip_selector_and_executor() -> None:
    executor = FakeExecutor()
    client = FakeSelectorClient(
        ToolSelection(
            selected_tool=None,
            confidence=1,
            reason_code="NO_TOOL",
        )
    )
    registry = build_tool_registry()
    settings = build_settings()
    service = ChatPipeline(
        FakeRouting(
            route=RouteType.UNSUPPORTED,
            domain=Domain.GENERAL,
            tool_name=None,
        ),  # type: ignore[arg-type]
        ToolSelector(client, registry),  # type: ignore[arg-type]
        ArgumentResolver(),
        ToolSelectionValidator(registry, settings),
        executor,  # type: ignore[arg-type]
        ToolResponseFormatter(),
        ConversationStore(settings.pending_action_ttl_seconds),
        registry,
    )

    result = await service.process("Thời tiết hôm nay?", trusted())

    assert result.type is ChatResponseType.UNSUPPORTED
    assert client.calls == 0
    assert executor.calls == 0


@pytest.mark.asyncio
async def test_low_selection_confidence_never_executes() -> None:
    executor = FakeExecutor()
    service = pipeline(
        FakeRouting(
            route=RouteType.STRUCTURED_QUERY,
            domain=Domain.LEAVE,
            tool_name="leave_get_balance",
        ),
        ToolSelection(
            selected_tool="leave_get_balance",
            confidence=0.2,
            extracted_arguments={"year": 2026},
            reason_code="LOW_CONFIDENCE",
        ),
        executor,
    )

    result = await service.process("Thông tin phép", trusted())

    assert result.type is ChatResponseType.CLARIFICATION_REQUIRED
    assert executor.calls == 0
