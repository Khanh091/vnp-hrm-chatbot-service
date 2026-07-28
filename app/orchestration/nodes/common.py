from datetime import date, datetime
from time import perf_counter
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.orchestration.state import ChatGraphState


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
    events.append({"type": event, "data": data or {}})
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
