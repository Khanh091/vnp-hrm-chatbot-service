from __future__ import annotations

import json
import logging

from app.answers.sanitizer import ToolResultSanitizer
from app.answers.schemas import FinalAnswerContext
from app.routing.schemas import QueryClassification
from app.tools.definitions import ToolExecutionResult

logger = logging.getLogger(__name__)


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
        sanitized = self._sanitizer.sanitize(
            intent=classification.intent,
            tool_name=tool_name,
            data=tool_result.data,
        )
        top_level_keys = (
            sorted(sanitized)
            if isinstance(sanitized, dict)
            else []
        )
        serialized_size = len(
            json.dumps(
                sanitized,
                ensure_ascii=False,
                default=str,
                separators=(",", ":"),
            )
        )
        logger.info(
            "final_answer_context intent=%s tool_name=%s "
            "top_level_keys=%s serialized_context_size=%s",
            classification.intent.value,
            tool_name,
            top_level_keys,
            serialized_size,
        )
        return FinalAnswerContext(
            original_query=original_query,
            route=classification.route,
            intent=classification.intent,
            operation=classification.operation,
            tool_name=tool_name,
            data=sanitized,
            locale=locale,
            timezone=timezone,
        )
