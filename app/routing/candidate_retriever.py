import logging
from time import perf_counter

from pydantic import BaseModel, ConfigDict, Field

from app.retrieval.embeddings import EmbeddingProvider
from app.retrieval.tool_indexer import retrieval_route
from app.retrieval.vector_store import VectorStore
from app.routing.schemas import (
    CandidateRetrievalRequest,
    Domain,
    Operation,
    RouteType,
    ToolCandidate,
)
from app.tools.registry import ToolNotFoundError, ToolRegistry

logger = logging.getLogger(__name__)

_HIGH_CONFIDENCE = 0.7


class CandidateRetrievalOutcome(BaseModel):
    model_config = ConfigDict(frozen=True)

    candidates: list[ToolCandidate]
    embedding_ms: float = Field(ge=0)
    vector_search_ms: float = Field(ge=0)
    fallback_reason: str | None = None


class CandidateRetriever:
    def __init__(
        self,
        registry: ToolRegistry,
        embedding_provider: EmbeddingProvider,
        vector_store: VectorStore,
    ) -> None:
        self._registry = registry
        self._embedding_provider = embedding_provider
        self._vector_store = vector_store
        self._supported_domains = tuple(
            dict.fromkeys(
                Domain(tool.domain.value)
                for tool in registry.list_all()
                if tool.enabled
            )
        )

    async def retrieve(
        self,
        request: CandidateRetrievalRequest,
    ) -> CandidateRetrievalOutcome:
        route_types = self._metadata_routes(request.classification.route_type)
        if not route_types:
            return CandidateRetrievalOutcome(
                candidates=[],
                embedding_ms=0,
                vector_search_ms=0,
                fallback_reason="ROUTE_HAS_NO_REGISTERED_TOOLS",
            )

        domains, fallback_reason = await self._select_domains(
            request,
            route_types,
        )
        if not domains:
            return CandidateRetrievalOutcome(
                candidates=[],
                embedding_ms=0,
                vector_search_ms=0,
                fallback_reason=fallback_reason or "NO_METADATA_CANDIDATES",
            )
        if fallback_reason is not None:
            logger.info(
                "candidate_retrieval_fallback reason_code=%s",
                fallback_reason,
            )

        embedding_started = perf_counter()
        embedding = await self._embedding_provider.embed_query(request.query)
        embedding_ms = (perf_counter() - embedding_started) * 1000

        search_started = perf_counter()
        matches = await self._vector_store.search(
            embedding=embedding,
            domains=tuple(domain.value for domain in domains),
            route_types=route_types,
            limit=request.effective_fetch_k,
        )
        vector_search_ms = (perf_counter() - search_started) * 1000

        candidates: list[ToolCandidate] = []
        for match in sorted(matches, key=lambda item: item.score, reverse=True):
            if match.score < request.min_score:
                continue
            try:
                tool = self._registry.get(match.tool_name)
            except ToolNotFoundError:
                continue
            if (
                not tool.enabled
                or tool.domain.value != match.domain
                or retrieval_route(tool) not in route_types
                or all(
                    scope.value != request.classification.scope.value
                    for scope in tool.supported_scopes
                )
            ):
                continue
            try:
                domain = Domain(match.domain)
                operation = Operation(match.operation)
            except ValueError:
                continue
            candidates.append(
                ToolCandidate(
                    tool_name=tool.name,
                    domain=domain,
                    capability=tool.capability,
                    operation=operation,
                    score=match.score,
                    rank=len(candidates) + 1,
                )
            )
            if len(candidates) == request.top_k:
                break

        return CandidateRetrievalOutcome(
            candidates=candidates,
            embedding_ms=embedding_ms,
            vector_search_ms=vector_search_ms,
            fallback_reason=fallback_reason,
        )

    async def _select_domains(
        self,
        request: CandidateRetrievalRequest,
        route_types: tuple[str, ...],
    ) -> tuple[tuple[Domain, ...], str | None]:
        classification = request.classification
        primary = classification.primary_domain
        if primary in self._supported_domains and await self._has(
            (primary,),
            route_types,
        ):
            return (primary,), None

        secondary = tuple(
            domain
            for domain in classification.secondary_domains
            if domain in self._supported_domains and domain is not primary
        )
        if secondary and await self._has(secondary, route_types):
            return secondary, "SECONDARY_DOMAIN_FALLBACK"

        if classification.confidence >= _HIGH_CONFIDENCE:
            return (), "HIGH_CONFIDENCE_FILTER_EMPTY"
        if classification.route_type is RouteType.TRANSACTION:
            return (), "TRANSACTION_DOMAIN_UNCLEAR"

        broader = tuple(
            domain
            for domain in self._supported_domains
            if domain is not primary and domain not in secondary
        )
        if broader and await self._has(broader, route_types):
            return broader, "LOW_CONFIDENCE_DOMAIN_EXPANSION"
        return (), "NO_METADATA_CANDIDATES"

    async def _has(
        self,
        domains: tuple[Domain, ...],
        route_types: tuple[str, ...],
    ) -> bool:
        return await self._vector_store.has_candidates(
            domains=tuple(domain.value for domain in domains),
            route_types=route_types,
        )

    @staticmethod
    def _metadata_routes(route_type: RouteType) -> tuple[str, ...]:
        if route_type is RouteType.TRANSACTION:
            return ("transaction",)
        if route_type in {RouteType.STRUCTURED_QUERY, RouteType.ANALYTICS}:
            return ("structured_query",)
        return ()
