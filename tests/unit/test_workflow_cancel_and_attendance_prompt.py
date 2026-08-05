from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.api.schemas.chat import ChatAction, ChatActionType
from app.context.conversation import ConversationStatus
from app.context.dialog_manager import DialogTurnManager
from app.orchestration.nodes.ask_clarification import ask_clarification_node
from app.orchestration.nodes.detect_turn_type import detect_turn_type_node
from app.orchestration.nodes.format_response import format_response_node
from app.orchestration.routes import route_after_turn_detection
from app.orchestration.state import ChatResponseType, TurnType
from app.routing.intent_refiner import direct_classify_from_exclusive_hints
from app.routing.query_normalizer import QueryNormalizer
from app.routing.rules import infer_rule_hints
from app.routing.schemas import Domain, QueryClassification
from app.routing.taxonomy import (
    Intent,
    Operation,
    QueryRoute,
    SubjectScope,
)
from app.tools import build_tool_registry
from app.tools.definitions import ToolExecutionResult
from app.workflows import SlotManager, build_workflow_registry


class _ConversationService:
    def __init__(self) -> None:
        self.cleared: list[tuple[str, int]] = []
        self.updated: list[dict[str, object]] = []

    async def load_owned(
        self, conversation_id: str, odoo_user_id: int
    ) -> object:
        return object()

    async def update(self, conversation: object, **values: object) -> None:
        self.updated.append(values)

    async def clear_active_workflow(
        self, conversation_id: str, odoo_user_id: int
    ) -> None:
        self.cleared.append((conversation_id, odoo_user_id))


def _runtime(service: _ConversationService) -> SimpleNamespace:
    return SimpleNamespace(
        context=SimpleNamespace(
            conversation_service=service,
            dialog_turn_manager=DialogTurnManager(),
            workflow_registry=build_workflow_registry(),
            slot_manager=SlotManager(),
        )
    )


def _clarification_state(tool_name: str) -> dict[str, object]:
    return {
        "conversation_id": "conversation-1",
        "request_id": "request-1",
        "pending_tool_name": tool_name,
        "missing_arguments": ["date_from", "date_to"],
        "ambiguous_arguments": [],
        "collected_arguments": {},
        "workflow_data": {},
        "classification": {},
        "candidate_contexts": [],
        "selection": {},
        "trusted_context": {"odoo_user_id": 17},
        "stage_timings": {},
        "graph_events": [],
        "current_step": 0,
    }


def test_full_attendance_query_routes_to_attendance_history() -> None:
    normalized = QueryNormalizer().normalize(
        "vắng bao nhiêu buổi, toàn bộ thông tin chấm công"
    )
    classification = direct_classify_from_exclusive_hints(
        normalized,
        infer_rule_hints(normalized),
    )

    assert classification is not None
    assert classification.intent is Intent.ATTENDANCE_HISTORY
    tools = build_tool_registry().find_tools(
        intent=classification.intent,
        domain=classification.domain.value,
        route=classification.route,
        operation=classification.operation,
        scope=classification.scope,
    )
    assert [tool.name for tool in tools] == ["attendance_get_history"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("missing", "expected"),
    (
        (["date_from", "date_to"], "Bạn muốn tra cứu từ ngày nào?"),
        (["date_to"], "Bạn muốn tra cứu đến ngày nào?"),
    ),
)
async def test_attendance_date_prompt_does_not_mention_leave(
    missing: list[str],
    expected: str,
) -> None:
    service = _ConversationService()
    state = _clarification_state("attendance_get_history")
    state["missing_arguments"] = missing

    update = await ask_clarification_node(
        state,
        _runtime(service),
    )

    assert update["response_text"] == expected
    assert "nghỉ" not in str(update["response_text"]).lower()
    assert update["response_data"]["missing_arguments"] == missing


@pytest.mark.asyncio
async def test_leave_clarification_exposes_cancel_workflow_button() -> None:
    service = _ConversationService()

    update = await ask_clarification_node(
        _clarification_state("leave_create_request"),
        _runtime(service),
    )

    assert update["response_text"] == "Bạn muốn bắt đầu nghỉ từ ngày nào?"
    assert update["response_data"]["actions"] == [
        {
            "type": "cancel_workflow",
            "label": "Tôi không muốn tạo đơn nghỉ",
        }
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("message", "action_type"),
    (("hủy", None), (None, "cancel_workflow")),
    ids=("typed-huy", "cancel-button"),
)
async def test_cancel_clears_pending_clarification(
    message: str | None,
    action_type: str | None,
) -> None:
    service = _ConversationService()
    state = {
        **_clarification_state("leave_create_request"),
        "conversation_status": (
            ConversationStatus.AWAITING_CLARIFICATION.value
        ),
        "user_message": message,
        "action_type": action_type,
        "clarification": None,
        "workflow_data": {"current_field": "date_from"},
    }

    update = await detect_turn_type_node(state, _runtime(service))

    assert update["turn_type"] is TurnType.WORKFLOW_CANCEL
    assert route_after_turn_detection(update) == "format_response"
    assert service.cleared == [("conversation-1", 17)]
    assert update["response_type"] is ChatResponseType.ANSWER
    assert update["response_text"] == "Đã hủy quy trình đang thực hiện."
    assert update["pending_tool_name"] is None


def test_cancel_workflow_action_does_not_require_pending_action_id() -> None:
    action = ChatAction(type=ChatActionType.CANCEL_WORKFLOW)

    assert action.action_id is None
    with pytest.raises(ValidationError):
        ChatAction(type=ChatActionType.CONFIRM)


@pytest.mark.asyncio
async def test_attendance_summary_uses_final_answer_service() -> None:
    class _ContextBuilder:
        def build(self, **values: object) -> object:
            return values

    class _FinalAnswerService:
        calls = 0

        async def stream_answer(self, context: object, **_: object):
            self.calls += 1
            assert isinstance(context, dict)
            yield "Tháng 2026-08, bạn có 1 ngày không chấm công."

    final_answers = _FinalAnswerService()
    runtime = SimpleNamespace(
        context=SimpleNamespace(
            response_formatter=SimpleNamespace(
                format=lambda *_args, **_kwargs: "FIXED_FORMATTER_OUTPUT"
            ),
            answer_context_builder=_ContextBuilder(),
            final_answer_service=final_answers,
        )
    )
    classification = QueryClassification(
        route=QueryRoute.DATA_QUERY,
        domain=Domain.ATTENDANCE,
        intent=Intent.ATTENDANCE_MONTHLY_SUMMARY,
        operation=Operation.READ,
        scope=SubjectScope.SELF,
        confidence=0.98,
        reason_code="TEST_ATTENDANCE",
    )
    state = {
        "request_id": "request-1",
        "user_message": "tháng này tôi chấm công thiếu mấy ngày",
        "classification": classification.model_dump(mode="json"),
        "workflow_data": {},
        "trusted_context": {
            "language": "vi_VN",
            "timezone": "Asia/Ho_Chi_Minh",
        },
        "tool_result": ToolExecutionResult(
            tool_name="attendance_get_monthly_summary",
            success=True,
            data={"month": "2026-08", "no_attendance_days": 1},
            latency_ms=1,
        ).model_dump(mode="json"),
        "stage_timings": {},
        "graph_events": [],
        "current_step": 0,
    }

    update = await format_response_node(state, runtime)

    assert final_answers.calls == 1
    assert update["response_text"] == (
        "Tháng 2026-08, bạn có 1 ngày không chấm công."
    )
    assert update["response_text"] != "FIXED_FORMATTER_OUTPUT"
