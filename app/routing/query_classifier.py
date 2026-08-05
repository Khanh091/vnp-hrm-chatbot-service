import logging

from app.context.entity_resolver import EntityResolver
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
from app.routing.intent_refiner import (
    RoutingCanonicalizationError,
    direct_classify_from_exclusive_hints,
    repair_classification,
)
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
        hints = infer_rule_hints(query)
        matched_concepts = [hint.concept for hint in hints.semantic_hints]
        direct = direct_classify_from_exclusive_hints(query, hints)
        if direct is not None:
            logger.info(
                "query_classified classifier_source=exclusive_rule "
                "classification_repaired=false matched_concepts=%s "
                "original_intent=%s final_intent=%s",
                matched_concepts,
                None,
                direct.intent.value if direct.intent else None,
            )
            return direct
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

        original_intent = result.intent
        subject = EntityResolver().extract_subject(query.original_text)
        try:
            repaired = repair_classification(result, subject, hints)
        except RoutingCanonicalizationError as error:
            logger.warning(
                "query_classification_failed reason_code=%s "
                "classifier_source=llm matched_concepts=%s",
                error.reason_code,
                matched_concepts,
            )
            raise QueryClassifierError(
                "Classification violates intent taxonomy",
                reason_code=error.reason_code,
            ) from error
        was_repaired = any(
            getattr(repaired, field) != getattr(result, field)
            for field in ("route", "domain", "operation", "scope", "intent")
        )
        result = repaired
        logger.info(
            "query_classified classifier_source=llm "
            "classification_repaired=%s matched_concepts=%s "
            "original_intent=%s final_intent=%s",
            was_repaired,
            matched_concepts,
            original_intent.value if original_intent else None,
            result.intent.value if result.intent else None,
        )
        # A strong explicit write signal cannot safely be downgraded to a read.
        if (
            hints.operation_hint is not None
            and hints.operation_hint.value in {"create", "update", "delete"}
            and result.route.value != "task"
        ):
            logger.warning(
                "query_classification_failed reason_code=WRITE_ROUTE_MISMATCH "
                "domain=%s intent=%s operation=%s route=%s",
                result.domain.value if result.domain else None,
                result.intent.value if result.intent else None,
                result.operation.value,
                result.route.value,
            )
            raise QueryClassifierError(
                "Classifier contradicted an explicit write action",
                reason_code="WRITE_ROUTE_MISMATCH",
            )
        return result
