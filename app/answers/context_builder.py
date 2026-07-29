from __future__ import annotations

from app.answers.sanitizer import ToolResultSanitizer
from app.answers.schemas import FinalAnswerContext
from app.routing.schemas import QueryClassification
from app.tools.definitions import ToolExecutionResult


class AnswerContextBuilder:
    def __init__(self, sanitizer: ToolResultSanitizer) -> None:
        self._sanitizer = sanitizer

    def build(
        self,
        *,
        original_query: str,
        classification: QueryClassification,
        tool_name: str,
        tool_result: ToolExecutionResult,
        locale: str,
        timezone: str,
    ) -> FinalAnswerContext:
        if classification.intent is None:
            raise ValueError("Final answer requires a classified intent")
        return FinalAnswerContext(
            original_query=original_query,
            route=classification.route,
            intent=classification.intent,
            operation=classification.operation,
            tool_name=tool_name,
            data=self._sanitizer.sanitize(
                intent=classification.intent,
                tool_name=tool_name,
                data=tool_result.data,
            ),
            locale=locale,
            timezone=timezone,
        )
