from __future__ import annotations

import re

from app.orchestration.state import TurnType

_CLEAR_NEW_INTENT = re.compile(
    r"\b("
    r"chấm công|lịch sử chấm công|check[- ]?in|check[- ]?out|"
    r"đi muộn|đi trễ|giờ vào|giờ ra|ngày công|"
    r"quên chấm công|ngày làm việc|"
    r"phòng ban|đơn vị công tác|chức danh|vị trí|"
    r"quản lý trực tiếp|cấp trên|sếp trực tiếp|"
    r"email|số điện thoại|hợp đồng|học vấn|bằng cấp|"
    r"tài khoản ngân hàng|"
    r"ngày phép còn lại|còn bao nhiêu ngày phép|"
    r"đã dùng (?:bao nhiêu|mấy) ngày phép|lịch sử nghỉ|"
    r"thông tin bảo hiểm|mã nhân (?:viên|sự)"
    r")\b",
    re.I,
)
_QUERY_OR_COMMAND = re.compile(
    r"\b(là gì|bao nhiêu|mấy|của tôi|cho tôi xem|chưa|"
    r"lịch sử|thông tin|tạo|hủy|cập nhật)\b",
    re.I,
)
_DATE_ANSWER = re.compile(
    r"^(?:"
    r"\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?|"
    r"hôm nay|hôm qua|ngày mai|"
    r"(?:đầu|cuối) (?:tuần|tháng)|"
    r"(?:tuần|tháng|năm) (?:này|trước|sau)|"
    r"quý\s*(?:i{1,3}|iv|[1-4])(?:\s+\d{4})?|"
    r"thứ (?:hai|ba|tư|năm|sáu|bảy|2|3|4|5|6|7)"
    r"(?: tuần (?:này|sau|trước))?"
    r")$",
    re.I,
)
_REQUEST_CODE = re.compile(r"^(?:LEAVE[-\s]?)?\d{1,12}$", re.I)
_NAMED_EMPLOYEE_QUERY = re.compile(
    r"\b[A-ZÀ-ỸĐ][\wÀ-ỹĐđ'-]+"
    r"(?:\s+[A-ZÀ-ỸĐ][\wÀ-ỹĐđ'-]+){1,5}"
    r"\s+(?:ở|thuộc|làm việc)\b"
)


class DialogTurnManager:
    """Deterministic turn routing around an active slot workflow."""

    def detect(
        self,
        *,
        message: str | None,
        structured_clarification: dict[str, object] | None,
        expected_field: str | None = None,
    ) -> TurnType:
        if structured_clarification is not None:
            return (
                TurnType.CLARIFICATION_ANSWER
                if structured_clarification.get("field") == expected_field
                else TurnType.CLARIFICATION_RETRY
            )
        text = (message or "").strip()
        if self._matches_expected_slot(text, expected_field):
            return TurnType.CLARIFICATION_ANSWER
        if _NAMED_EMPLOYEE_QUERY.search(text):
            return TurnType.NEW_QUERY_OVERRIDE
        if _CLEAR_NEW_INTENT.search(text) and (
            _QUERY_OR_COMMAND.search(text)
            or expected_field in {"date", "date_from", "date_to"}
        ):
            return TurnType.NEW_QUERY_OVERRIDE
        return TurnType.CLARIFICATION_RETRY

    @staticmethod
    def _matches_expected_slot(text: str, expected_field: str | None) -> bool:
        if not text or expected_field is None:
            return False
        if expected_field in {"date", "date_from", "date_to"}:
            return bool(_DATE_ANSWER.fullmatch(text))
        if expected_field in {"leave_request_id", "leave_request_code"}:
            return bool(_REQUEST_CODE.fullmatch(text))
        if expected_field in {"leave_type_id", "reason"}:
            return not bool(_CLEAR_NEW_INTENT.search(text))
        return False
