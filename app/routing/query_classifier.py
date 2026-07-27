import logging

from app.llm.client import LlmClientError, StructuredOutputClient
from app.llm.prompts import (
    QUERY_CLASSIFIER_SYSTEM_PROMPT,
    build_query_classifier_prompt,
)
from app.llm.structured_output import StructuredOutputError
from app.routing.rules import infer_rule_hints
from app.routing.schemas import NormalizedQuery, QueryClassification

logger = logging.getLogger(__name__)


class QueryClassifierError(RuntimeError):
    pass


class QueryClassifier:
    def __init__(self, llm_client: StructuredOutputClient) -> None:
        self._llm_client = llm_client

    async def classify(self, query: NormalizedQuery) -> QueryClassification:
        hints = infer_rule_hints(query.normalized_text)
        try:
            result = await self._llm_client.complete_structured(
                system_prompt=QUERY_CLASSIFIER_SYSTEM_PROMPT,
                user_prompt=build_query_classifier_prompt(query, hints),
                schema=QueryClassification,
            )
        except (LlmClientError, StructuredOutputError) as error:
            logger.warning(
                "query_classification_failed reason_code=%s",
                type(error).__name__.upper(),
            )
            raise QueryClassifierError("Query classification failed") from error

        # A strong explicit write signal cannot safely be downgraded to a read.
        if (
            hints.operation_hint is not None
            and result.route_type.value != "transaction"
        ):
            logger.warning(
                "query_classification_failed reason_code=WRITE_ROUTE_MISMATCH"
            )
            raise QueryClassifierError(
                "Classifier contradicted an explicit write action"
            )
        return result
