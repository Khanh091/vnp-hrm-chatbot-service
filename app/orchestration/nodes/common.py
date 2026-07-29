from collections.abc import Callable
from contextvars import ContextVar, Token
from datetime import date, datetime
from time import perf_counter
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.orchestration.state import ChatGraphState, TurnType

GraphEventSink = Callable[[dict[str, Any]], None]
graph_event_sink: ContextVar[GraphEventSink | None] = ContextVar(
    "graph_event_sink",
    default=None,
)


def set_graph_event_sink(sink: GraphEventSink) -> Token[GraphEventSink | None]:
    return graph_event_sink.set(sink)


def reset_graph_event_sink(token: Token[GraphEventSink | None]) -> None:
    graph_event_sink.reset(token)


def emit_graph_event(event: str, data: dict[str, Any]) -> None:
    sink = graph_event_sink.get()
    if sink is not None:
        sink({"type": event, "data": data})


def elapsed_ms(started: float) -> float:
    return max(0.0, (perf_counter() - started) * 1000)


def stage_update(
    state: ChatGraphState,
    *,
    event: str,
    timing_name: str | None = None,
    started: float | None = None,
    data: dict[str, Any] | None = None,
) -> dict[str, object]:
    timings = dict(state.get("stage_timings", {}))
    if timing_name is not None and started is not None:
        timings[timing_name] = elapsed_ms(started)
    events = [*state.get("graph_events", [])]
    graph_event = {"type": event, "data": data or {}}
    events.append(graph_event)
    sink = graph_event_sink.get()
    if sink is not None:
        sink(graph_event)
    return {
        "current_step": state.get("current_step", 0) + 1,
        "stage_timings": timings,
        "graph_events": events,
    }


def trusted_today(timezone_name: str) -> date:
    try:
        zone = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        zone = ZoneInfo("UTC")
    return datetime.now(zone).date()


def public_arguments(arguments: dict[str, Any]) -> dict[str, Any]:
    hidden = {
        "idempotency_key",
        "odoo_user_id",
        "employee_id",
        "company_id",
        "request_id",
    }
    return {key: value for key, value in arguments.items() if key not in hidden}


def routing_context_value(
    state: ChatGraphState,
    field: str,
) -> Any:
    """Prefer persisted routing context while resuming clarification."""

    persisted = state.get("workflow_data", {}).get(field)
    turn_type = state.get("turn_type")
    if (
        turn_type
        in {
            TurnType.CLARIFICATION_ANSWER,
            TurnType.CLARIFICATION_RETRY,
            "clarification_answer",
            "clarification_retry",
        }
        and persisted
    ):
        return persisted
    return state.get(field) or persisted
