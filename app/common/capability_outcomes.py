from __future__ import annotations

from enum import Enum
from typing import Any

from app.routing.taxonomy import Intent


class CapabilityOutcome(str, Enum):
    SUCCESS = "success"
    EMPTY = "empty"
    UNSUPPORTED = "unsupported"
    DENIED = "denied"
    NOT_FOUND = "not_found"
    INVALID = "invalid"


_UNSUPPORTED_CODES = {
    "INTENT_NOT_RECOGNIZED",
    "NO_CANDIDATES",
    "NO_CANDIDATE_TOOL",
    "NO_CAPABILITY_FOR_INTENT",
    "NO_MATCHING_TOOL",
    "NO_METADATA_CANDIDATES",
    "NO_REGISTERED_TOOL",
    "NO_RETRIEVAL_CANDIDATES",
    "NO_SUBJECT_COMPATIBLE_TOOL",
    "NO_TOOL",
    "NO_TOOL_FOR_CAPABILITY",
    "ROUTE_HAS_NO_REGISTERED_TOOLS",
    "TOOL_NOT_FOUND",
}
_EMPTY_CODES = {"SUPPORTED_EMPTY"}
_DENIED_CODES = {
    "ACCESS_DENIED",
    "ACTION_ACCESS_DENIED",
    "CONVERSATION_ACCESS_DENIED",
    "RESOURCE_ACCESS_DENIED",
    "SECURITY_REJECTED",
    "SCOPE_NOT_ALLOWED",
}
_NOT_FOUND_CODES = {
    "ACTOR_DEPARTMENT_NOT_FOUND",
    "ENTITY_NOT_FOUND",
    "EMPLOYEE_NOT_FOUND",
    "RECORD_NOT_FOUND",
    "SELF_EMPLOYEE_NOT_LINKED",
    "SUBJECT_NOT_FOUND",
}
_INVALID_CODES = {
    "INVALID",
    "INVALID_ARGUMENT",
    "INVALID_ARGUMENTS",
    "MISSING_ARGUMENT",
    "MISSING_REQUIRED_ARGUMENT",
    "TOOL_SELECTION_FAILED",
}

_INTENT_LABELS = {
    Intent.PROFILE_FAMILY_RELATIONS: "quan hệ gia đình",
    Intent.PROFILE_PERSONAL_BACKGROUND: "lý lịch cá nhân",
    Intent.PROFILE_FAMILY_ECONOMY: "kinh tế gia đình",
    Intent.PROFILE_HEALTH: "thông tin sức khỏe",
}


def outcome_for_error(reason_code: str | None) -> CapabilityOutcome:
    code = (reason_code or "").strip().upper()
    if code in _EMPTY_CODES:
        return CapabilityOutcome.EMPTY
    if code in _DENIED_CODES:
        return CapabilityOutcome.DENIED
    if code in _NOT_FOUND_CODES:
        return CapabilityOutcome.NOT_FOUND
    if code in _UNSUPPORTED_CODES:
        return CapabilityOutcome.UNSUPPORTED
    if code in _INVALID_CODES:
        return CapabilityOutcome.INVALID
    return CapabilityOutcome.INVALID


def outcome_for_success(data: Any) -> CapabilityOutcome:
    return (
        CapabilityOutcome.SUCCESS
        if _has_meaningful_value(data)
        else CapabilityOutcome.EMPTY
    )


def public_outcome_message(
    outcome: CapabilityOutcome,
    *,
    capability_label: str | None = None,
) -> str:
    if outcome is CapabilityOutcome.UNSUPPORTED:
        if capability_label:
            return f"Hiện chatbot chưa hỗ trợ tra cứu {capability_label}."
        return "Hiện chatbot chưa hỗ trợ chức năng này."
    if outcome is CapabilityOutcome.EMPTY:
        return "Hệ thống chưa lưu thông tin này."
    if outcome is CapabilityOutcome.DENIED:
        return "Bạn không có quyền truy cập thông tin này."
    if outcome is CapabilityOutcome.NOT_FOUND:
        return "Không tìm thấy đối tượng phù hợp."
    if outcome is CapabilityOutcome.INVALID:
        return "Thông tin bạn cung cấp chưa hợp lệ."
    return ""


def capability_label_for_intent(intent: Intent | str | None) -> str | None:
    if intent is None:
        return None
    try:
        normalized = intent if isinstance(intent, Intent) else Intent(intent)
    except ValueError:
        return None
    return _INTENT_LABELS.get(normalized)


def _has_meaningful_value(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, bool):
        return True
    if isinstance(value, (int, float)):
        return True
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, dict):
        return any(_has_meaningful_value(item) for item in value.values())
    if isinstance(value, (list, tuple, set, frozenset)):
        return any(_has_meaningful_value(item) for item in value)
    return True
