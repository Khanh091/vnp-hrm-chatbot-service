from __future__ import annotations

import logging
from collections.abc import AsyncIterator

from app.answers.fallback import DeterministicAnswerFallback
from app.answers.prompts import (
    FINAL_ANSWER_SYSTEM_PROMPT,
    build_final_answer_prompt,
)
from app.answers.schemas import FinalAnswerContext
from app.llm.client import TextStreamingClient
from app.llm.exceptions import LlmClientError

logger = logging.getLogger(__name__)


class FinalAnswerService:
    def __init__(
        self,
        client: TextStreamingClient,
        fallback: DeterministicAnswerFallback,
        *,
        temperature: float,
        max_tokens: int,
    ) -> None:
        self._client = client
        self._fallback = fallback
        self._temperature = temperature
        self._max_tokens = max_tokens

    async def stream_answer(
        self,
        context: FinalAnswerContext,
        *,
        request_id: str,
    ) -> AsyncIterator[str]:
        emitted = False
        try:
            async for chunk in self._client.stream_text(
                system_prompt=FINAL_ANSWER_SYSTEM_PROMPT,
                user_prompt=build_final_answer_prompt(context),
                max_tokens=self._max_tokens,
                temperature=self._temperature,
                operation="final_answer",
                request_id=request_id,
            ):
                cleaned_chunk = chunk.replace("*", "")
                if cleaned_chunk:
                    emitted = True
                    yield cleaned_chunk
            if not emitted:
                raise ValueError("EMPTY_FINAL_ANSWER_STREAM")
        except (LlmClientError, ValueError) as error:
            reason_code = (
                type(error).__name__.upper()
                if isinstance(error, LlmClientError)
                else "EMPTY_FINAL_ANSWER"
            )
            logger.warning(
                "final_answer_llm_failed fallback_used=true "
                "reason_code=%s request_id=%s",
                reason_code,
                request_id,
            )
            yield self._fallback.format(context)
