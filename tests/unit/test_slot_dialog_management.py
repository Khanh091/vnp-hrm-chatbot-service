from datetime import date

import pytest
from pydantic import ValidationError

from app.api.schemas.chat import ClarificationAnswer
from app.context.date_resolver import (
    AmbiguousDateExpression,
    DateResolver,
)
from app.context.dialog_manager import DialogTurnManager
from app.context.entities import ExtractedEntities
from app.context.entity_resolver import BusinessEntityResolver, EntityResolver
from app.orchestration.nodes.merge_clarification import (
    merge_workflow_metadata,
)
from app.orchestration.state import TurnType
from app.workflows import SlotManager, build_workflow_registry

TODAY = date(2026, 7, 29)


def create_leave_workflow():
    workflow = build_workflow_registry().get("leave_create_request")
    assert workflow is not None
    return workflow


def test_create_leave_slots_are_filled_one_at_a_time() -> None:
    manager = SlotManager()
    workflow = create_leave_workflow()
    state = manager.initialize(workflow)
    assert manager.get_next_slot(workflow, state) == "date_from"

    state = manager.merge(
        workflow,
        state,
        {"date_from": date(2026, 7, 29)},
    )
    assert manager.get_next_slot(workflow, state) == "date_to"

    state = manager.merge(
        workflow,
        state,
        {"date_to": date(2026, 7, 30)},
    )
    assert manager.get_next_slot(workflow, state) == "leave_type_id"

    state = manager.merge(workflow, state, {"leave_type_id": 5})
    assert manager.get_next_slot(workflow, state) == "reason"

    state = manager.merge(
        workflow,
        state,
        {"reason": "Việc cá nhân"},
    )
    assert manager.get_next_slot(workflow, state) is None
    assert state.missing == []
    assert state.issues == []


def test_invalid_date_range_never_becomes_complete() -> None:
    manager = SlotManager()
    workflow = create_leave_workflow()
    state = manager.initialize(
        workflow,
        {
            "date_from": date(2026, 7, 30),
            "date_to": date(2026, 7, 29),
            "leave_type_id": 5,
        },
    )

    assert any(issue.code == "INVALID_DATE_RANGE" for issue in state.issues)


def test_temporal_resolver_handles_explicit_date_and_ambiguity() -> None:
    resolver = DateResolver()
    resolved = resolver.resolve(
        "29/7/2026",
        current_date=TODAY,
        timezone="Asia/Ho_Chi_Minh",
    )
    assert resolved is not None
    assert resolved.date_from == date(2026, 7, 29)
    with pytest.raises(AmbiguousDateExpression):
        resolver.resolve(
            "thứ hai",
            current_date=TODAY,
            timezone="Asia/Ho_Chi_Minh",
        )


def test_clear_new_intent_overrides_pending_date_slot() -> None:
    manager = DialogTurnManager()
    assert (
        manager.detect(
            message="Hôm qua tôi chấm công chưa",
            structured_clarification=None,
            expected_field="date_from",
        )
        is TurnType.NEW_QUERY_OVERRIDE
    )
    assert (
        manager.detect(
            message="Phòng ban của tôi là gì",
            structured_clarification=None,
            expected_field="date_from",
        )
        is TurnType.NEW_QUERY_OVERRIDE
    )
    assert (
        manager.detect(
            message="29/7/2026",
            structured_clarification=None,
            expected_field="date_from",
        )
        is TurnType.CLARIFICATION_ANSWER
    )


def test_structured_clarification_has_optional_label() -> None:
    answer = ClarificationAnswer(field="leave_type_id", value=5)
    assert answer.value == 5
    assert answer.label is None
    options = BusinessEntityResolver.leave_type_options(
        {"items": [{"id": 5, "name": "Phép năm"}]}
    )
    matched = BusinessEntityResolver.match_leave_type("phép năm", options)
    assert matched is not None
    assert matched.value == 5


def test_extracted_entities_reject_untrusted_technical_ids() -> None:
    with pytest.raises(ValidationError):
        ExtractedEntities.model_validate({"leave_type_id": 5})

    extracted = EntityResolver().extract(
        "Tạo đơn nghỉ phép năm ngày 29/7/2026 vì việc gia đình"
    )
    assert extracted.temporal.date == "29/7/2026"
    assert extracted.business.leave_type_text == "phép năm"
    assert extracted.business.reason == "việc gia đình"


def test_slot_state_survives_serialization_restart() -> None:
    manager = SlotManager()
    workflow = create_leave_workflow()
    before = manager.initialize(
        workflow,
        {"date_from": date(2026, 7, 29)},
    )
    restored = type(before).model_validate(
        before.model_dump(mode="json")
    )
    after = manager.merge(
        workflow,
        restored,
        {"date_to": date(2026, 7, 30)},
    )

    assert after.values["date_from"] == "2026-07-29"
    assert manager.get_next_slot(workflow, after) == "leave_type_id"


def test_slot_manager_clear_removes_all_pending_values() -> None:
    cleared = SlotManager.clear()
    assert cleared.values == {}
    assert cleared.missing == []
    assert cleared.ambiguous == []


def test_leave_type_options_survive_later_reason_turn() -> None:
    original = {
        "clarification_options": [
            {"value": 3, "label": "Không lương"},
        ]
    }

    updated = merge_workflow_metadata(
        original,
        options=[],
        slot_issues=[],
    )

    assert updated["clarification_options"] == [
        {"value": 3, "label": "Không lương"},
    ]
