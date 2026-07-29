from typing import Literal

from app.orchestration.state import (
    ChatGraphState,
    TurnType,
    WorkflowStatus,
)


def route_after_turn_detection(
    state: ChatGraphState,
) -> Literal[
    "normalize_query",
    "merge_clarification",
    "load_pending_action_confirm",
    "load_pending_action_cancel",
]:
    routes = {
        TurnType.NEW_QUERY: "normalize_query",
        TurnType.NEW_QUERY_OVERRIDE: "normalize_query",
        TurnType.CLARIFICATION_ANSWER: "merge_clarification",
        TurnType.CLARIFICATION_RETRY: "merge_clarification",
        TurnType.CONFIRMATION_ACCEPT: "load_pending_action_confirm",
        TurnType.CONFIRMATION_CANCEL: "load_pending_action_cancel",
    }
    return routes[state["turn_type"]]  # type: ignore[return-value]


def route_after_selection(
    state: ChatGraphState,
) -> Literal["resolve_arguments", "format_response"]:
    return (
        "resolve_arguments"
        if state.get("pending_tool_name")
        else "format_response"
    )


def route_after_classification(
    state: ChatGraphState,
) -> Literal["retrieve_candidates", "format_response"]:
    return (
        "format_response"
        if state.get("response_type") is not None
        else "retrieve_candidates"
    )


def route_after_retrieval(
    state: ChatGraphState,
) -> Literal["select_tool", "format_response"]:
    return (
        "format_response"
        if state.get("response_type") is not None
        else "select_tool"
    )


def route_after_clarification_merge(
    state: ChatGraphState,
) -> Literal["resolve_arguments", "format_response"]:
    return (
        "format_response"
        if state.get("response_type") is not None
        else "resolve_arguments"
    )


def route_after_validation(
    state: ChatGraphState,
) -> Literal[
    "ask_clarification",
    "create_confirmation",
    "execute_read_tool",
    "format_response",
]:
    routes = {
        WorkflowStatus.CLARIFICATION_REQUIRED: "ask_clarification",
        WorkflowStatus.CONFIRMATION_REQUIRED: "create_confirmation",
        WorkflowStatus.EXECUTE_READ: "execute_read_tool",
    }
    status = state.get("workflow_status")
    if status is None:
        return "format_response"
    return routes.get(status, "format_response")  # type: ignore[return-value]
