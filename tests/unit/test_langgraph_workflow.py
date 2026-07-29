import pytest
from pydantic import ValidationError

from app.api.schemas.chat import ChatRequest
from app.orchestration.graph import build_chat_graph
from app.orchestration.nodes.common import routing_context_value
from app.orchestration.routes import (
    route_after_selection,
    route_after_turn_detection,
    route_after_validation,
)
from app.orchestration.state import (
    TurnType,
    WorkflowStatus,
)
from app.workflows import build_workflow_registry


def test_graph_compiles_with_all_business_nodes_reachable() -> None:
    graph = build_chat_graph().get_graph()
    required = {
        "load_conversation",
        "detect_turn_type",
        "normalize_query",
        "classify_query",
        "retrieve_candidates",
        "select_tool",
        "merge_clarification",
        "validate_selection",
        "ask_clarification",
        "create_confirmation",
        "execute_read_tool",
        "execute_write_tool",
        "cancel_pending_action",
        "persist_conversation",
    }
    assert required <= set(graph.nodes)
    assert any(edge.source == "__start__" for edge in graph.edges)
    assert any(edge.target == "__end__" for edge in graph.edges)


@pytest.mark.parametrize(
    ("turn_type", "expected"),
    [
        (TurnType.NEW_QUERY, "normalize_query"),
        (TurnType.CLARIFICATION_ANSWER, "merge_clarification"),
        (TurnType.CONFIRMATION_ACCEPT, "load_pending_action_confirm"),
        (TurnType.CONFIRMATION_CANCEL, "load_pending_action_cancel"),
    ],
)
def test_turn_routes_are_deterministic(
    turn_type: TurnType, expected: str
) -> None:
    assert route_after_turn_detection({"turn_type": turn_type}) == expected


def test_validation_routes_are_deterministic() -> None:
    assert (
        route_after_validation(
            {"workflow_status": WorkflowStatus.CLARIFICATION_REQUIRED}
        )
        == "ask_clarification"
    )
    assert (
        route_after_validation(
            {"workflow_status": WorkflowStatus.CONFIRMATION_REQUIRED}
        )
        == "create_confirmation"
    )
    assert (
        route_after_validation(
            {"workflow_status": WorkflowStatus.EXECUTE_READ}
        )
        == "execute_read_tool"
    )
    assert route_after_selection({"pending_tool_name": None}) == "format_response"


def test_chat_request_requires_exactly_one_input() -> None:
    with pytest.raises(ValidationError):
        ChatRequest()
    with pytest.raises(ValidationError):
        ChatRequest(
            message="x",
            conversation_id="conv-1",
            action={
                "type": "confirm",
                "action_id": "act-00000000-0000-0000-0000-000000000000",
            },
        )


def test_action_requires_conversation_id() -> None:
    with pytest.raises(ValidationError):
        ChatRequest(
            action={
                "type": "cancel",
                "action_id": "act-00000000-0000-0000-0000-000000000000",
            }
        )


def test_structured_clarification_requires_conversation_id() -> None:
    with pytest.raises(ValidationError):
        ChatRequest(
            clarification={
                "field": "leave_type_id",
                "value": 5,
                "label": "Phép năm",
            }
        )


def test_leave_workflow_asks_one_field_in_configured_order() -> None:
    workflow = build_workflow_registry().get("leave_create_request")
    assert workflow is not None
    assert (
        workflow.next_field(
            ["leave_type_id", "date_to", "date_from"], []
        )
        == "date_from"
    )


def test_clarification_uses_persisted_routing_context() -> None:
    persisted = {
        "route": "data_query",
        "domain": "attendance",
        "intent": "attendance.daily",
        "operation": "read",
        "scope": "self",
        "confidence": 0.95,
    }
    state = {
        "turn_type": TurnType.CLARIFICATION_ANSWER,
        "classification": {"domain": None, "operation": "none"},
        "candidate_contexts": [],
        "workflow_data": {
            "classification": persisted,
            "candidate_contexts": [{"tool_name": "attendance_get_daily"}],
        },
    }

    assert routing_context_value(state, "classification") == persisted
    assert routing_context_value(state, "candidate_contexts") == [
        {"tool_name": "attendance_get_daily"}
    ]
