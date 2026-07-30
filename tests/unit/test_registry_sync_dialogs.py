from __future__ import annotations

from app.context.dialog_manager import DialogTurnManager
from app.context.entity_memory import (
    ConversationEntityMemory,
    EntityMemoryService,
)
from app.context.entity_resolver import EntityResolver
from app.orchestration.state import TurnType
from app.routing.intent_refiner import refine_read_intent
from app.routing.schemas import Domain, QueryClassification
from app.routing.taxonomy import (
    Intent,
    Operation,
    QueryRoute,
    SubjectScope,
)
from app.tools import build_tool_registry


def _seed() -> QueryClassification:
    return QueryClassification(
        route=QueryRoute.DATA_QUERY,
        domain=Domain.GENERAL,
        intent=Intent.ATTENDANCE_DAILY,
        operation=Operation.READ,
        scope=SubjectScope.SELF,
        confidence=0.6,
    )


def test_leave_status_then_latest_reference_uses_memory() -> None:
    registry = build_tool_registry()
    first = refine_read_intent(
        "trạng thái đơn nghỉ phép của tôi",
        _seed(),
    )
    tools = registry.find_tools(
        intent=first.intent,
        domain=first.domain.value if first.domain else None,
        route=first.route,
        operation=first.operation,
        scope=first.scope,
    )
    assert {tool.name for tool in tools} == {
        "leave_get_history",
        "leave_get_request_status",
    }

    memory_service = EntityMemoryService()
    memory = memory_service.capture(
        tool_name="leave_get_history",
        data={
            "records": [
                {
                    "id": 321,
                    "code": "LEAVE-00321",
                    "date_from": "2026-07-29",
                    "date_to": "2026-07-30",
                    "state": "approve",
                }
            ]
        },
        memory=ConversationEntityMemory(),
    )
    mention = EntityResolver().extract_subject("đơn gần nhất")
    reference = memory_service.resolve_leave_request(mention, memory)

    assert reference is not None
    assert reference.entity_id == 321
    assert reference.label.startswith("LEAVE-00321")


def test_sticky_leave_flow_is_overridden_by_two_read_queries() -> None:
    manager = DialogTurnManager()
    registry = build_tool_registry()

    turn_two = "số lần quên chấm công của tôi"
    assert manager.detect(
        message=turn_two,
        structured_clarification=None,
        expected_field="date_from",
    ) is TurnType.NEW_QUERY_OVERRIDE
    attendance = refine_read_intent(turn_two, _seed())
    attendance_tools = registry.find_tools(
        intent=attendance.intent,
        domain=attendance.domain.value if attendance.domain else None,
        route=attendance.route,
        operation=attendance.operation,
        scope=attendance.scope,
    )
    assert [tool.name for tool in attendance_tools] == [
        "attendance_get_monthly_summary"
    ]

    turn_three = "số ngày phép còn lại"
    leave = refine_read_intent(turn_three, _seed())
    leave_tools = registry.find_tools(
        intent=leave.intent,
        domain=leave.domain.value if leave.domain else None,
        route=leave.route,
        operation=leave.operation,
        scope=leave.scope,
    )
    assert [tool.name for tool in leave_tools] == ["leave_get_balance"]
    assert all(
        tool.name != "leave_create_request"
        for tool in (*attendance_tools, *leave_tools)
    )


def test_semantic_metadata_contains_required_distinctions() -> None:
    registry = build_tool_registry()
    employment = registry.get("employee_get_employment")
    create_leave = registry.get("leave_create_request")
    monthly = registry.get("attendance_get_monthly_summary")

    assert Intent.DIRECTORY_EMPLOYEE_DEPARTMENT in employment.intents
    assert Intent.PROFILE_DEPARTMENT in employment.intents
    assert any(
        "danh sách nhân viên" in text.casefold()
        for text in employment.negative_examples
    )
    assert any(
        "trạng thái đơn nghỉ" in text.casefold()
        for text in create_leave.negative_examples
    )
    assert any(
        "tạo đơn nghỉ" in text.casefold()
        for text in monthly.negative_examples
    )
