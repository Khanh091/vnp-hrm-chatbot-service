import logging

from app.llm.client import LlmClientError, StructuredOutputClient
from app.llm.exceptions import (
    LlmBadRequestError,
    LlmRateLimitError,
    LlmStructuredOutputError,
    LlmTimeoutError,
)
from app.llm.prompts import (
    QUERY_CLASSIFIER_SYSTEM_PROMPT,
    build_query_classifier_prompt,
)
from app.llm.structured_output import StructuredOutputError
from app.routing.input_guardrail import InputGuardrail
from app.routing.intent_refiner import refine_read_intent
from app.routing.rules import infer_rule_hints
from app.routing.schemas import NormalizedQuery, QueryClassification

logger = logging.getLogger(__name__)


class QueryClassifierError(RuntimeError):
    def __init__(self, message: str, *, reason_code: str) -> None:
        super().__init__(message)
        self.reason_code = reason_code


class QueryClassifier:
    def __init__(
        self,
        llm_client: StructuredOutputClient,
        guardrail: InputGuardrail | None = None,
    ) -> None:
        self._llm_client = llm_client
        self._guardrail = guardrail or InputGuardrail()

    async def classify(self, query: NormalizedQuery) -> QueryClassification:
        guarded = self._guardrail.inspect(query.normalized_text)
        if guarded is not None:
            return guarded
        hints = infer_rule_hints(query.normalized_text)
        try:
            result = await self._llm_client.complete_structured(
                system_prompt=QUERY_CLASSIFIER_SYSTEM_PROMPT,
                user_prompt=build_query_classifier_prompt(query, hints),
                schema=QueryClassification,
                operation="query_classification",
            )
        except (LlmClientError, StructuredOutputError) as error:
            if isinstance(error, LlmRateLimitError):
                reason_code = "LLM_RATE_LIMITED"
            elif isinstance(error, LlmTimeoutError):
                reason_code = "LLM_TIMEOUT"
            elif isinstance(
                error,
                (LlmStructuredOutputError, LlmBadRequestError),
            ):
                reason_code = "LLM_BAD_RESPONSE"
            else:
                reason_code = "LLM_PROVIDER_UNAVAILABLE"
            logger.warning(
                "query_classification_failed reason_code=%s",
                reason_code,
            )
            raise QueryClassifierError(
                "Query classification failed",
                reason_code=reason_code,
            ) from error

        result = refine_read_intent(query.normalized_text, result)
        # A strong explicit write signal cannot safely be downgraded to a read.
        if (
            hints.operation_hint is not None
            and result.route.value != "task"
        ):
            logger.warning(
                "query_classification_failed reason_code=WRITE_ROUTE_MISMATCH"
            )
            raise QueryClassifierError(
                "Classifier contradicted an explicit write action",
                reason_code="WRITE_ROUTE_MISMATCH",
            )
        return result
