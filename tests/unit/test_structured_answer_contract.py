from datetime import date

import pytest
from pydantic import ValidationError

from app.api.schemas.chat import ChatRequest
from app.workflows.structured_answer import (
    InvalidStructuredSelection,
    validate_structured_selection,
)

OPTIONS = [
    {"value": "1", "label": "Nghỉ phép"},
    {"value": "2", "label": "Không lương"},
]


def structured_request(**answer: str) -> ChatRequest:
    return ChatRequest.model_validate(
        {
            "conversation_id": "conversation-structured",
            "structured_answer": answer,
        }
    )


def test_1_option_select_payload_matches_chat_request_schema() -> None:
    request = structured_request(
        type="option_select",
        slot_name="leave_type_id",
        selected_value="2",
        display_label="Không lương",
    )

    assert request.message is None
    assert request.structured_answer is not None
    assert request.structured_answer.selected_value == "2"


def test_2_extra_structured_field_is_forbidden() -> None:
    with pytest.raises(ValidationError) as captured:
        structured_request(
            type="option_select",
            slot_name="leave_type_id",
            selected_value="2",
            display_label="Không lương",
            employee_id="123",
        )

    assert any(
        item["type"] == "extra_forbidden" for item in captured.value.errors()
    )


def test_3_allowed_option_is_merged_with_trusted_label() -> None:
    selection = validate_structured_selection(
        {
            "answer_type": "option_select",
            "field": "leave_type_id",
            "value": "2",
            "label": "Nội dung frontend không được tin cậy",
        },
        expected_field="leave_type_id",
        allowed_options=OPTIONS,
    )

    assert selection.business_value == "2"
    assert selection.display_label == "Không lương"


def test_4_option_outside_allowlist_is_rejected() -> None:
    with pytest.raises(InvalidStructuredSelection):
        validate_structured_selection(
            {
                "answer_type": "option_select",
                "field": "leave_type_id",
                "value": "999",
            },
            expected_field="leave_type_id",
            allowed_options=OPTIONS,
        )


def test_5_date_select_iso_value_is_merged_as_date() -> None:
    request = structured_request(
        type="date_select",
        slot_name="date_from",
        selected_value="2026-08-10",
        display_label="10/08/2026",
    )
    assert request.structured_answer is not None
    selection = validate_structured_selection(
        {
            "answer_type": request.structured_answer.type.value,
            "field": request.structured_answer.slot_name,
            "value": request.structured_answer.selected_value,
        },
        expected_field="date_from",
        allowed_options=[],
        metadata={"min_date": "2026-08-03"},
    )

    assert selection.business_value == date(2026, 8, 10)
    assert selection.display_label == "10/08/2026"


def test_6_slot_name_must_match_expected_slot() -> None:
    with pytest.raises(InvalidStructuredSelection):
        validate_structured_selection(
            {
                "answer_type": "option_select",
                "field": "date_to",
                "value": "2",
            },
            expected_field="leave_type_id",
            allowed_options=OPTIONS,
        )


def test_7_profile_field_edit_is_bounded_to_session_and_field() -> None:
    request = ChatRequest.model_validate({
        "conversation_id": "conversation-profile",
        "structured_answer": {
            "type": "profile_field_edit",
            "session_id": "profile-session-1",
            "field_key": "mobile_phone",
            "value": "0987654321",
            "display_label": "0987654321",
        },
    })
    assert request.structured_answer.field_key == "mobile_phone"
    assert request.structured_answer.value == "0987654321"


def test_8_profile_edit_action_rejects_unknown_action() -> None:
    with pytest.raises(ValidationError):
        ChatRequest.model_validate({
            "conversation_id": "conversation-profile",
            "structured_answer": {
                "type": "profile_edit_action",
                "session_id": "profile-session-1",
                "action": "execute_now",
            },
        })


def test_9_profile_override_actions_are_bounded() -> None:
    request = ChatRequest.model_validate({
        "conversation_id": "conversation-profile",
        "structured_answer": {
            "type": "profile_edit_action",
            "session_id": "profile-session-1",
            "action": "switch_discard",
        },
    })
    assert request.structured_answer.action == "switch_discard"
