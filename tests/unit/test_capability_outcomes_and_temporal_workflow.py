from datetime import date
from types import SimpleNamespace

import pytest

from app.common.capability_outcomes import (
    CapabilityOutcome,
    capability_label_for_intent,
    outcome_for_error,
    outcome_for_success,
    public_outcome_message,
)
from app.context.conversation import ConversationStatus
from app.context.date_resolver import DateResolver
from app.context.dialog_manager import DialogTurnManager
from app.orchestration.nodes.detect_turn_type import detect_turn_type_node
from app.orchestration.state import TurnType
from app.routing.taxonomy import Intent

TRUSTED_TODAY = date(2026, 7, 31)
TRUSTED_TIMEZONE = "Asia/Ho_Chi_Minh"


def test_create_leave_then_mai_is_high_confidence_date_answer() -> None:
    assert (
        DialogTurnManager().detect(
            message="mai",
            structured_clarification=None,
            expected_field="date_from",
        )
        is TurnType.CLARIFICATION_ANSWER
    )
    resolved = DateResolver().resolve(
        "mai",
        current_date=TRUSTED_TODAY,
        timezone=TRUSTED_TIMEZONE,
    )
    assert resolved is not None
    assert resolved.date_from == date(2026, 8, 1)


def test_create_leave_then_mot_is_high_confidence_date_answer() -> None:
    assert (
        DialogTurnManager().detect(
            message="mốt",
            structured_clarification=None,
            expected_field="date_from",
        )
        is TurnType.CLARIFICATION_ANSWER
    )
    resolved = DateResolver().resolve(
        "mốt",
        current_date=TRUSTED_TODAY,
        timezone=TRUSTED_TIMEZONE,
    )
    assert resolved is not None
    assert resolved.date_from == date(2026, 8, 2)


@pytest.mark.asyncio
async def test_attendance_history_overrides_and_clears_pending_date() -> None:
    class ConversationService:
        cleared: list[tuple[str, int]] = []

        async def clear_active_workflow(
            self, conversation_id: str, user_id: int
        ) -> None:
            self.cleared.append((conversation_id, user_id))

    service = ConversationService()
    runtime = SimpleNamespace(
        context=SimpleNamespace(
            dialog_turn_manager=DialogTurnManager(),
            conversation_service=service,
        )
    )
    state = {
        "conversation_id": "conversation-1",
        "conversation_status": (
            ConversationStatus.AWAITING_CLARIFICATION.value
        ),
        "user_message": "lịch sử chấm công",
        "clarification": None,
        "trusted_context": {"odoo_user_id": 17},
        "workflow_data": {"current_field": "date_from"},
        "pending_tool_name": "leave_create_request",
        "collected_arguments": {"reason": "Việc riêng"},
    }

    update = await detect_turn_type_node(state, runtime)

    assert update["turn_type"] is TurnType.NEW_QUERY_OVERRIDE
    assert service.cleared == [("conversation-1", 17)]
    assert update["pending_tool_name"] is None
    assert update["workflow_data"] == {}


def test_unsupported_profile_capability_uses_public_label() -> None:
    outcome = outcome_for_error("NO_CAPABILITY_FOR_INTENT")
    label = capability_label_for_intent(Intent.PROFILE_HEALTH)

    assert outcome is CapabilityOutcome.UNSUPPORTED
    assert (
        public_outcome_message(outcome, capability_label=label)
        == "Hiện chatbot chưa hỗ trợ tra cứu thông tin sức khỏe."
    )


def test_supported_but_empty_has_distinct_outcome() -> None:
    outcome = outcome_for_success(None)

    assert outcome is CapabilityOutcome.EMPTY
    assert outcome_for_error("SUPPORTED_EMPTY") is CapabilityOutcome.EMPTY
    assert public_outcome_message(outcome) == "Hệ thống chưa lưu thông tin này."


def test_access_denied_has_distinct_outcome() -> None:
    outcome = outcome_for_error("ACCESS_DENIED")

    assert outcome is CapabilityOutcome.DENIED
    assert (
        public_outcome_message(outcome)
        == "Bạn không có quyền truy cập thông tin này."
    )


def test_false_boolean_is_valid_data() -> None:
    assert (
        outcome_for_success({"is_party_member": False})
        is CapabilityOutcome.SUCCESS
    )


def test_empty_list_is_preserved_and_classified_empty() -> None:
    payload = {"items": []}

    assert outcome_for_success(payload) is CapabilityOutcome.EMPTY
    assert payload == {"items": []}
