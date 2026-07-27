from time import perf_counter

from app.routing.candidate_retriever import CandidateRetriever
from app.routing.query_classifier import QueryClassifier
from app.routing.query_normalizer import QueryNormalizer
from app.routing.schemas import (
    CandidateRetrievalRequest,
    RoutingDebugResult,
    RoutingStageTimings,
)


class RoutingService:
    def __init__(
        self,
        normalizer: QueryNormalizer,
        classifier: QueryClassifier,
        retriever: CandidateRetriever,
        *,
        top_k: int,
        fetch_k: int,
        min_score: float,
    ) -> None:
        self._normalizer = normalizer
        self._classifier = classifier
        self._retriever = retriever
        self._top_k = top_k
        self._fetch_k = fetch_k
        self._min_score = min_score

    async def route(self, message: str) -> RoutingDebugResult:
        started = perf_counter()
        normalized = self._normalizer.normalize(message)
        normalization_ms = (perf_counter() - started) * 1000

        started = perf_counter()
        classification = await self._classifier.classify(normalized)
        classification_ms = (perf_counter() - started) * 1000

        outcome = await self._retriever.retrieve(
            CandidateRetrievalRequest(
                query=normalized.normalized_text,
                classification=classification,
                top_k=self._top_k,
                fetch_k=self._fetch_k,
                min_score=self._min_score,
            )
        )
        return RoutingDebugResult(
            normalized_query=normalized.normalized_text,
            classification=classification,
            candidates=outcome.candidates,
            timings=RoutingStageTimings(
                normalization_ms=normalization_ms,
                classification_ms=classification_ms,
                embedding_ms=outcome.embedding_ms,
                vector_search_ms=outcome.vector_search_ms,
            ),
        )
