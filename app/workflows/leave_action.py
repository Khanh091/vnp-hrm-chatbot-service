from __future__ import annotations

from datetime import date
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class LeaveRequestSnapshot(BaseModel):
    model_config = ConfigDict(extra="allow", frozen=True)

    request_id: int = Field(gt=0)
    date_from: date
    date_to: date
    leave_type_id: int = Field(gt=0)
    leave_type: str
    reason: str = ""
    state: str = ""
    state_label: str = ""
    can_update: bool = False
    can_cancel: bool = False
    version: str | int | None = None


CHANGE_FIELD_OPTIONS = (
    {"value": "date_from", "label": "Ngày bắt đầu"},
    {"value": "date_to", "label": "Ngày kết thúc"},
    {"value": "leave_type_id", "label": "Loại nghỉ"},
    {"value": "reason", "label": "Lý do"},
    {"value": "multiple", "label": "Sửa nhiều thông tin"},
)

CREATE_FIELD_LABELS = {
    "date_from": "Ngày bắt đầu",
    "date_to": "Ngày kết thúc",
    "leave_type": "Loại nghỉ",
    "reason": "Lý do",
}


def records_from_payload(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    if not isinstance(data, dict):
        return []
    for key in (
        "actionable_requests",
        "requests",
        "records",
        "items",
        "data",
        "result",
    ):
        value = data.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    return []


def actionable_options(data: Any) -> list[dict[str, str]]:
    options: list[dict[str, str]] = []
    for record in records_from_payload(data):
        request_id = record.get("request_id") or record.get("id")
        if not isinstance(request_id, int) or request_id <= 0:
            continue
        date_from = _display_date(record.get("date_from"))
        date_to = _display_date(record.get("date_to"))
        leave_type = _leave_type_name(record)
        state = _state_label(record)
        label = " · ".join(
            value
            for value in (
                f"{date_from}–{date_to}" if date_from and date_to else date_from,
                leave_type,
                state,
            )
            if value
        )
        days = record.get("number_of_days", record.get("duration_days"))
        reason = str(record.get("reason") or "").strip()
        description = " · ".join(
            value
            for value in (
                f"{days:g} ngày" if isinstance(days, (int, float)) else "",
                reason,
            )
            if value
        )
        options.append(
            {
                "value": str(request_id),
                "label": label or "Đơn nghỉ phép",
                "description": description,
            }
        )
    return options


def trusted_selected_request(
    options: list[dict[str, Any]], selected_value: Any
) -> int | None:
    matched = next(
        (item for item in options if str(item.get("value")) == str(selected_value)),
        None,
    )
    if matched is None:
        return None
    try:
        value = int(str(matched["value"]))
    except (KeyError, TypeError, ValueError):
        return None
    return value if value > 0 else None


def snapshot_from_payload(data: Any) -> LeaveRequestSnapshot:
    value = data
    if isinstance(data, dict):
        for key in ("request", "details", "data", "result"):
            nested = data.get(key)
            if isinstance(nested, dict):
                value = nested
                break
    if not isinstance(value, dict):
        raise ValueError("invalid leave request details")
    leave_type = value.get("leave_type")
    leave_type_id = value.get("leave_type_id")
    leave_type_name = value.get("leave_type_name")
    if isinstance(leave_type, dict):
        leave_type_id = leave_type_id or leave_type.get("id")
        leave_type_name = (
            leave_type_name or leave_type.get("name") or leave_type.get("display_name")
        )
    request_id = value.get("request_id") or value.get("id")
    if request_id is None or leave_type_id is None:
        raise ValueError("leave request identity is missing")
    return LeaveRequestSnapshot(
        request_id=int(request_id),
        date_from=date.fromisoformat(str(value["date_from"])[:10]),
        date_to=date.fromisoformat(str(value["date_to"])[:10]),
        leave_type_id=int(leave_type_id),
        leave_type=str(leave_type_name or "Loại nghỉ"),
        reason=str(value.get("reason") or ""),
        state=str(value.get("state") or ""),
        state_label=str(value.get("state_label") or _state_label(value)),
        can_update=bool(value.get("can_update")),
        can_cancel=bool(value.get("can_cancel")),
        version=value.get("version") or value.get("write_date"),
    )


def validated_patch(
    snapshot: LeaveRequestSnapshot,
    changes: dict[str, Any],
) -> dict[str, Any]:
    allowed = {"date_from", "date_to", "leave_type_id", "reason"}
    normalized: dict[str, Any] = {}
    for field, value in changes.items():
        if field not in allowed or value is None:
            continue
        if field in {"date_from", "date_to"}:
            value = date.fromisoformat(str(value)[:10]).isoformat()
        elif field == "leave_type_id":
            value = int(value)
            if value <= 0:
                raise ValueError("invalid leave type")
        elif field == "reason":
            value = str(value).strip()
            if not value:
                raise ValueError("reason is empty")
        original = getattr(snapshot, field)
        original_value = (
            original.isoformat() if isinstance(original, date) else original
        )
        if value != original_value:
            normalized[field] = value
    effective_from = date.fromisoformat(
        str(normalized.get("date_from", snapshot.date_from))[:10]
    )
    effective_to = date.fromisoformat(
        str(normalized.get("date_to", snapshot.date_to))[:10]
    )
    if effective_from > effective_to:
        raise ValueError("invalid leave date range")
    if not normalized:
        raise ValueError("no changed fields")
    return normalized


def confirmation_summary(
    snapshot: LeaveRequestSnapshot,
    changes: dict[str, Any],
    *,
    leave_type_label: str | None = None,
) -> dict[str, Any]:
    labels = {
        "date_from": "Ngày bắt đầu",
        "date_to": "Ngày kết thúc",
        "leave_type_id": "Loại nghỉ",
        "reason": "Lý do",
    }
    rows: list[dict[str, str]] = []
    for field, value in changes.items():
        before: Any = getattr(snapshot, field)
        after: Any = value
        if field in {"date_from", "date_to"}:
            before = _display_date(before)
            after = _display_date(after)
        elif field == "leave_type_id":
            before = snapshot.leave_type
            after = leave_type_label or str(value)
        rows.append(
            {
                "field": field,
                "label": labels[field],
                "from": str(before),
                "to": str(after),
            }
        )
    return {
        "selected_request": (
            f"{_display_date(snapshot.date_from)}–{_display_date(snapshot.date_to)}"
            f" · {snapshot.leave_type} · {snapshot.state_label or snapshot.state}"
        ),
        "changes": rows,
    }


def create_confirmation_summary(
    arguments: dict[str, Any],
    *,
    leave_type_label: str,
) -> dict[str, Any]:
    """Build the same bounded row contract rendered by ConfirmationCard."""

    values = {
        "date_from": arguments.get("date_from"),
        "date_to": arguments.get("date_to"),
        "leave_type": leave_type_label,
        "reason": arguments.get("reason"),
    }
    rows = []
    for field, value in values.items():
        if value in (None, ""):
            continue
        if field in {"date_from", "date_to"}:
            value = _display_date(value)
        rows.append(
            {
                "field": field,
                "label": CREATE_FIELD_LABELS[field],
                "to": str(value),
            }
        )
    return {"changes": rows}


def _display_date(value: Any) -> str:
    if value in (None, ""):
        return ""
    try:
        parsed = (
            value if isinstance(value, date) else date.fromisoformat(str(value)[:10])
        )
    except ValueError:
        return str(value)
    return parsed.strftime("%d/%m/%Y")


def _leave_type_name(record: dict[str, Any]) -> str:
    value = record.get("leave_type_name") or record.get("leave_type")
    if isinstance(value, dict):
        value = value.get("name") or value.get("display_name")
    return str(value or "")


def _state_label(record: dict[str, Any]) -> str:
    explicit = record.get("state_label")
    if explicit:
        return str(explicit)
    return {
        "draft": "Nháp",
        "confirm": "Chờ duyệt",
        "wait_approve": "Chờ duyệt",
        "approve": "Đã duyệt",
        "reject": "Từ chối",
        "cancel": "Đã hủy",
    }.get(str(record.get("state") or "").casefold(), "")
