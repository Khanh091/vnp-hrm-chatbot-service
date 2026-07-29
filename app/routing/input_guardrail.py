import re

from app.routing.schemas import Domain, QueryClassification
from app.routing.taxonomy import Intent, Operation, QueryRoute, SubjectScope

_PROMPT_INJECTION = re.compile(
    r"\b(?:ignore|bỏ qua|quên)\b.{0,40}\b(?:instruction|chỉ dẫn|system prompt)\b"
    r"|\b(?:reveal|hiển thị|in ra)\b.{0,30}\b(?:system prompt|api key|secret)\b",
    re.IGNORECASE,
)
_FORBIDDEN_ADMIN = re.compile(
    r"\b(?:drop|truncate)\s+(?:database|table)\b"
    r"|\b(?:grant|cấp)\b.{0,30}\b(?:admin|quản trị viên)\b",
    re.IGNORECASE,
)


class InputGuardrail:
    """Deterministic security boundary; it never performs intent routing."""

    def inspect(self, text: str) -> QueryClassification | None:
        if _PROMPT_INJECTION.search(text):
            return self._unsafe(Intent.UNSAFE_PROMPT_INJECTION)
        if _FORBIDDEN_ADMIN.search(text):
            return self._unsafe(Intent.UNSAFE_FORBIDDEN_ADMIN_ACTION)
        return None

    @staticmethod
    def _unsafe(intent: Intent) -> QueryClassification:
        return QueryClassification(
            route=QueryRoute.UNSAFE,
            domain=Domain.GENERAL,
            intent=intent,
            operation=Operation.NONE,
            scope=SubjectScope.UNKNOWN,
            confidence=1.0,
            reason_code="INPUT_GUARDRAIL_REJECTED",
        )
