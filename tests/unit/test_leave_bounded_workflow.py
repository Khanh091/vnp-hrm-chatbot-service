import json
from datetime import datetime, timezone
from types import SimpleNamespace

import httpx
import pytest

from app.answers.prompts import build_final_answer_prompt
from app.answers.schemas import FinalAnswerContext
from app.api.schemas.chat import ChatRequest
from app.common.error_messages import public_error_message
from app.context.conversation import PendingActionStatus
from app.context.entity_memory import ConversationEntityMemory, EntityMemoryService
from app.context.entity_resolver import BusinessEntityResolver, EntityResolver
from app.context.pending_action_service import PendingActionError, PendingActionService
from app.integrations.odoo.client import OdooClient
from app.orchestration.nodes.create_confirmation import create_confirmation_node
from app.routing.rules import infer_rule_hints
from app.routing.taxonomy import Intent, Operation, QueryRoute
from app.tools import build_tool_registry
from app.tools.definitions import ToolExecutionResult, TrustedExecutionContext
from app.tools.executor import ToolExecutor
from app.tools.response_formatter import ToolResponseFormatter
from app.workflows.leave_action import (
    LeaveRequestSnapshot,
    actionable_options,
    create_confirmation_summary,
    trusted_selected_request,
    validated_patch,
)
from app.workflows.registry import build_workflow_registry
from tests.conftest import build_settings

ACTIONABLE = {
    "actionable_requests": [
        {
            "request_id": 123,
            "date_from": "2026-08-10",
            "date_to": "2026-08-12",
            "leave_type_name": "Không lương",
            "state": "draft",
            "number_of_days": 3,
            "reason": "Việc cá nhân",
        },
        {
            "request_id": 99,
            "date_from": "2026-08-05",
            "date_to": "2026-08-05",
            "leave_type_name": "Nghỉ phép",
            "state": "confirm",
            "number_of_days": 1,
            "reason": "Gia đình",
        },
    ]
}


def snapshot() -> LeaveRequestSnapshot:
    return LeaveRequestSnapshot(
        request_id=123,
        date_from="2026-08-10",
        date_to="2026-08-11",
        leave_type_id=1,
        leave_type="Nghỉ phép",
        reason="Việc cá nhân",
        state="draft",
        state_label="Nháp",
        can_update=True,
        can_cancel=True,
        version="2026-08-03T08:00:00Z",
    )


def result(data: dict) -> ToolExecutionResult:
    return ToolExecutionResult(
        tool_name="test",
        success=True,
        data=data,
        latency_ms=1,
    )


def test_update_multiple_requests_returns_structured_options() -> None:
    payload = {
        "type": "entity_select",
        "entity_type": "leave_request",
        "prompt": "Bạn muốn sửa đơn nghỉ nào?",
        "options": actionable_options(ACTIONABLE),
    }

    assert payload["type"] == "entity_select"
    assert payload["options"][0] == {
        "value": "123",
        "label": "10/08/2026–12/08/2026 · Không lương · Nháp",
        "description": "3 ngày · Việc cá nhân",
    }
    assert len(payload["options"]) == 2


def test_update_latest_request_uses_first_odoo_sorted_item() -> None:
    service = EntityMemoryService()
    memory = service.capture(
        tool_name="leave_list_actionable_requests",
        data=ACTIONABLE,
        memory=ConversationEntityMemory(),
    )
    mention = EntityResolver().extract_subject("sửa đơn gần nhất")

    selected = service.resolve_leave_request(mention, memory)

    assert selected is not None
    assert selected.entity_id == 123
    assert selected.ordinal == 1


def test_update_button_selection_must_belong_to_saved_options() -> None:
    request = ChatRequest.model_validate(
        {
            "conversation_id": "conversation-1",
            "structured_answer": {
                "type": "option_select",
                "slot_name": "leave_request_id",
                "selected_value": "123",
                "display_label": "10/08/2026–12/08/2026 · Không lương · Nháp",
            },
        }
    )
    options = actionable_options(ACTIONABLE)

    assert request.structured_answer is not None
    assert request.structured_answer.slot_name == "leave_request_id"
    assert trusted_selected_request(options, "123") == 123
    assert trusted_selected_request(options, "777") is None


def test_update_reason_only_does_not_require_dates_or_leave_type() -> None:
    patch = validated_patch(snapshot(), {"reason": "bận việc hôm 12/8"})

    assert patch == {"reason": "bận việc hôm 12/8"}
    assert "date_from" not in patch
    assert "date_to" not in patch
    assert "leave_type_id" not in patch


@pytest.mark.asyncio
async def test_update_payload_excludes_self_from_overlap_by_path_identity() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "PUT"
        assert request.url.path == "/api/hrm-chatbot/v1/leave/requests/123"
        body = json.loads(request.content)
        assert body == {
            "date_to": "2026-08-12",
            "idempotency_key": "update-123",
            "odoo_user_id": 42,
        }
        return httpx.Response(
            200,
            json={
                "success": True,
                "code": "SUCCESS",
                "message": "ok",
                "data": {"request_id": 123},
                "meta": {
                    "request_id": "request-1",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                },
            },
        )

    client = OdooClient(build_settings(), transport=httpx.MockTransport(handler))
    try:
        execution = await ToolExecutor(build_tool_registry(), client).execute(
            "leave_update_request",
            {
                "request_id": 123,
                "changes": {"date_to": "2026-08-12"},
                "idempotency_key": "update-123",
            },
            context=TrustedExecutionContext(
                odoo_user_id=42,
                request_id="request-1",
            ),
            confirmed=True,
        )
    finally:
        await client.close()

    assert execution.success is True


def test_overlap_with_other_request_has_specific_message() -> None:
    assert public_error_message("LEAVE_REQUEST_OVERLAP") == (
        "Khoảng nghỉ mới bị trùng với một đơn nghỉ khác."
    )


def test_leave_type_button_keeps_label_and_description() -> None:
    options = BusinessEntityResolver.leave_type_options(
        {
            "leave_types": [
                {
                    "id": 2,
                    "name": "Không lương",
                    "description": "Không yêu cầu số dư phép",
                }
            ]
        }
    )

    assert options[0].value == 2
    assert options[0].label == "Không lương"
    assert options[0].description == "Không yêu cầu số dư phép"


def test_create_confirmation_uses_renderable_rows() -> None:
    summary = create_confirmation_summary(
        {
            "date_from": "2026-08-05",
            "date_to": "2026-08-05",
            "leave_type_id": 2,
            "reason": "bận việc",
            "request_unit": "day",
        },
        leave_type_label="Không lương",
    )

    assert summary == {
        "changes": [
            {
                "field": "date_from",
                "label": "Ngày bắt đầu",
                "to": "05/08/2026",
            },
            {
                "field": "date_to",
                "label": "Ngày kết thúc",
                "to": "05/08/2026",
            },
            {
                "field": "leave_type",
                "label": "Loại nghỉ",
                "to": "Không lương",
            },
            {"field": "reason", "label": "Lý do", "to": "bận việc"},
        ]
    }


@pytest.mark.asyncio
async def test_create_confirmation_node_returns_live_card_metadata() -> None:
    captured = {}

    class PendingActions:
        async def create(self, **values):
            captured["pending"] = values
            return SimpleNamespace(
                action_id="action-create-leave",
                expires_at=datetime(2026, 8, 5, 9, 34, tzinfo=timezone.utc),
            )

    class Conversations:
        async def load_owned(self, conversation_id, odoo_user_id):
            return SimpleNamespace(
                conversation_id=conversation_id,
                odoo_user_id=odoo_user_id,
            )

        async def update(self, conversation, **values):
            captured["conversation"] = values

    runtime = SimpleNamespace(
        context=SimpleNamespace(
            tool_registry=build_tool_registry(),
            workflow_registry=build_workflow_registry(),
            pending_action_service=PendingActions(),
            conversation_service=Conversations(),
        )
    )
    update = await create_confirmation_node(
        {
            "conversation_id": "conversation-create-leave",
            "pending_tool_name": "leave_create_request",
            "trusted_context": {"odoo_user_id": 42},
            "collected_arguments": {
                "date_from": "2026-08-05",
                "date_to": "2026-08-05",
                "leave_type_id": 2,
                "reason": "bận việc",
                "request_unit": "day",
                "idempotency_key": "create-leave-1",
            },
            "workflow_data": {
                "leave_type_options": [{"value": "2", "label": "Không lương"}]
            },
        },
        runtime,
    )

    card = update["response_data"]
    assert card["action"] == "create"
    assert card["confirm_label"] == "Xác nhận tạo đơn nghỉ phép"
    assert card["summary"]["changes"][2]["to"] == "Không lương"
    assert card["summary"]["changes"][3]["to"] == "bận việc"
    assert captured["pending"]["display_summary"] == card["summary"]


def test_leave_balance_uses_pending_breakdown_without_inference() -> None:
    answer = ToolResponseFormatter().format(
        "leave_get_balance",
        result(
            {
                "allocated_days": 17,
                "approved_used_days": 5,
                "pending_days": 5,
                "draft_days": 2,
                "remaining_days": 12,
                "available_days": 7,
                "validity": "2026-12-31",
            }
        ),
    )

    assert "tổng hạn mức 17 ngày" in answer
    assert "đã dùng 5 ngày và còn 12 ngày" in answer
    assert "sử dụng 7 ngày theo tiến độ tích lũy" in answer
    assert "5 ngày chờ duyệt và 2 ngày nháp" in answer
    assert "không giữ số dư phép" in answer


def test_leave_balance_llm_prompt_requires_annual_and_current_breakdown() -> None:
    prompt = build_final_answer_prompt(
        FinalAnswerContext(
            original_query="Tôi còn bao nhiêu ngày phép?",
            route=QueryRoute.DATA_QUERY,
            intent=Intent.LEAVE_BALANCE,
            operation=Operation.READ,
            tool_name="leave_get_balance",
            data={
                "allocated_days": 12,
                "approved_used_days": 0,
                "remaining_days": 12,
                "available_days": 8,
                "pending_reserves_allocation": False,
                "draft_reserves_allocation": False,
            },
            locale="vi_VN",
            timezone="Asia/Ho_Chi_Minh",
        )
    )

    assert "phân biệt rõ tổng hạn mức năm" in prompt
    assert "mức khả dụng hiện tại theo tiến độ tích lũy" in prompt
    assert "không mô tả phần chênh lệch là ngày đã nghỉ" in prompt


def test_attendance_monthly_preserves_odoo_business_fields() -> None:
    data = {
        "month": "08/2026",
        "actual_work_days": 19.5,
        "attendance_record_days": 21,
        "total_worked_hours": 156.25,
        "source": "hr.attendance.monthly",
    }
    formatter = ToolResponseFormatter()
    hints = infer_rule_hints("tháng này tôi chấm công bao nhiêu ngày")

    recorded = formatter.format(
        "attendance_get_monthly_summary",
        result(data),
        intent=Intent.ATTENDANCE_RECORDED_DAYS,
    )
    actual = formatter.format(
        "attendance_get_monthly_summary",
        result(data),
        intent=Intent.ATTENDANCE_ACTUAL_WORK_DAYS,
    )

    assert "21 ngày có bản ghi chấm công" in recorded
    assert "19.5 ngày công thực tế" in actual
    assert data["total_worked_hours"] == 156.25
    assert data["source"] == "hr.attendance.monthly"
    assert hints.semantic_hints[0].candidate_intents == (
        Intent.ATTENDANCE_RECORDED_DAYS,
    )


def test_confirmation_replay_never_reopens_executed_action() -> None:
    with pytest.raises(PendingActionError) as error:
        PendingActionService._raise_terminal_status(PendingActionStatus.EXECUTED.value)

    assert error.value.code == "ACTION_ALREADY_EXECUTED"
