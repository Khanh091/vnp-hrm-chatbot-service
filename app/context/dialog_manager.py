import re

from app.orchestration.state import TurnType

_CLEAR_NEW_INTENT = re.compile(
    r"\b("
    r"chấm công|check[- ]?in|check[- ]?out|đi muộn|đi trễ|"
    r"phòng ban|đơn vị công tác|chức danh|quản lý trực tiếp|"
    r"email|số điện thoại|hợp đồng|học vấn|"
    r"còn bao nhiêu ngày phép|đã dùng bao nhiêu ngày phép"
    r")\b",
    re.IGNORECASE,
)
_QUERY_OR_COMMAND = re.compile(
    r"\b(là gì|bao nhiêu|của tôi|cho tôi xem|chưa|tạo|hủy|cập nhật)\b",
    re.IGNORECASE,
)


class DialogTurnManager:
    """Deterministic turn routing around an active slot workflow."""

    def detect(
        self,
        *,
        message: str | None,
        structured_clarification: dict[str, object] | None,
    ) -> TurnType:
        if structured_clarification is not None:
            return TurnType.CLARIFICATION_ANSWER
        text = (message or "").strip()
        if _CLEAR_NEW_INTENT.search(text) and _QUERY_OR_COMMAND.search(text):
            return TurnType.NEW_QUERY
        return TurnType.CLARIFICATION_ANSWER
