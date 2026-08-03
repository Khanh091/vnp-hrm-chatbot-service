import json
from datetime import datetime, timezone

import httpx
import pytest

from app.api.schemas.chat import ChatRequest
from app.common.error_messages import public_error_message
from app.context.conversation import PendingActionStatus
from app.context.entity_memory import ConversationEntityMemory, EntityMemoryService
from app.context.entity_resolver import BusinessEntityResolver, EntityResolver
from app.context.pending_action_service import PendingActionError, PendingActionService
from app.integrations.odoo.client import OdooClient
from app.routing.rules import infer_rule_hints
from app.routing.taxonomy import Intent
from app.tools import build_tool_registry
from app.tools.definitions import ToolExecutionResult, TrustedExecutionContext
from app.tools.executor import ToolExecutor
from app.tools.response_formatter import ToolResponseFormatter
from app.workflows.leave_action import (
    LeaveRequestSnapshot,
    actionable_options,
    trusted_selected_request,
    validated_patch,
)
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
