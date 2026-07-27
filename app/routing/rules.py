import re

from app.routing.schemas import Domain, Operation, RouteType, RuleHints

_CREATE = re.compile(
    r"(?:^|\b(?:hãy|giúp tôi|tôi muốn)\s+)"
    r"(tạo|đăng ký|lập|gửi yêu cầu)\b",
    re.IGNORECASE,
)
_UPDATE = re.compile(r"\b(sửa|cập nhật|điều chỉnh|đổi)\b", re.IGNORECASE)
_CANCEL = re.compile(r"\b(hủy|huỷ|rút yêu cầu|xóa bỏ)\b", re.IGNORECASE)
_LEAVE_CONTEXT = re.compile(
    r"\b(đơn nghỉ|nghỉ phép|xin nghỉ|phép năm)\b",
    re.IGNORECASE,
)


def infer_rule_hints(normalized_text: str) -> RuleHints:
    """Return strong pre-hints only; this never selects a final tool."""

    operation: Operation | None = None
    reason_code: str | None = None
    if _CANCEL.search(normalized_text):
        operation = Operation.CANCEL
        reason_code = "EXPLICIT_CANCEL_ACTION"
    elif _UPDATE.search(normalized_text):
        operation = Operation.UPDATE
        reason_code = "EXPLICIT_UPDATE_ACTION"
    elif _CREATE.search(normalized_text):
        operation = Operation.CREATE
        reason_code = "EXPLICIT_CREATE_ACTION"

    if operation is None:
        return RuleHints()

    domain = (
        Domain.LEAVE if _LEAVE_CONTEXT.search(normalized_text) else None
    )
    return RuleHints(
        route_hint=RouteType.TRANSACTION,
        domain_hint=domain,
        operation_hint=operation,
        confidence=0.9 if domain is not None else 0.75,
        reason_code=reason_code,
    )
