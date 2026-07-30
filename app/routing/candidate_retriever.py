import logging
from time import perf_counter

from pydantic import BaseModel, ConfigDict, Field

from app.retrieval.embeddings import EmbeddingProvider
from app.retrieval.tool_indexer import retrieval_route
from app.retrieval.vector_store import VectorStore
from app.routing.intent_tool_mapping import tool_supports_intent
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


class RoutingInvariantError(RuntimeError):
    def __init__(self, reason_code: str) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code


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
        classification = request.classification
        direct_matches = self._registry.find_tools(
            intent=classification.intent,
            domain=(
                classification.domain.value
                if classification.domain is not None
                else None
            ),
            route=classification.route,
            operation=(
                None
                if classification.operation is Operation.NONE
                else classification.operation
            ),
            scope=classification.scope,
        )
        if classification.intent is not None and len(direct_matches) == 1:
            tool = direct_matches[0]
            self._enforce_operation_invariant(
                classification.operation,
                (tool,),
            )
            return CandidateRetrievalOutcome(
                candidates=[
                    ToolCandidate(
                        tool_name=tool.name,
                        domain=Domain(tool.domain.value),
                        capability=tool.capability,
                        operation=tool.query_operation,
                        score=1.0,
                        rank=1,
                    )
                ],
                embedding_ms=0,
                vector_search_ms=0,
                fallback_reason="DIRECT_INTENT_MAPPING",
            )

        route_types = self._metadata_routes(request.classification.route_type)
        operations = self._metadata_operations(classification.operation)
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
            operations,
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
            operations=operations,
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
                or (
                    classification.operation is not Operation.NONE
                    and tool.query_operation is not classification.operation
                )
                or (
                    classification.intent is not None
                    and not tool_supports_intent(
                        tool.name,
                        classification.intent,
                    )
                )
                or all(
                    subject_type.value
                    != (
                        "employee"
                        if request.classification.scope.value
                        == "named_employee"
                        else request.classification.scope.value
                    )
                    for subject_type in tool.supported_subject_types
                )
            ):
                continue
            try:
                domain = Domain(match.domain)
            except ValueError:
                continue
            candidates.append(
                ToolCandidate(
                    tool_name=tool.name,
                    domain=domain,
                    capability=tool.capability,
                    operation=tool.query_operation,
                    score=match.score,
                    rank=len(candidates) + 1,
                )
            )
            if len(candidates) == request.top_k:
                break

        return CandidateRetrievalOutcome(
            candidates=self._validated_candidates(
                classification.operation,
                candidates,
            ),
            embedding_ms=embedding_ms,
            vector_search_ms=vector_search_ms,
            fallback_reason=fallback_reason,
        )

    async def _select_domains(
        self,
        request: CandidateRetrievalRequest,
        route_types: tuple[str, ...],
        operations: tuple[str, ...],
    ) -> tuple[tuple[Domain, ...], str | None]:
        classification = request.classification
        primary = classification.primary_domain
        if primary in self._supported_domains and await self._has(
            (primary,),
            route_types,
            operations,
        ):
            return (primary,), None

        secondary = tuple(
            domain
            for domain in classification.secondary_domains
            if domain in self._supported_domains and domain is not primary
        )
        if secondary and await self._has(secondary, route_types, operations):
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
        if broader and await self._has(broader, route_types, operations):
            return broader, "LOW_CONFIDENCE_DOMAIN_EXPANSION"
        return (), "NO_METADATA_CANDIDATES"

    async def _has(
        self,
        domains: tuple[Domain, ...],
        route_types: tuple[str, ...],
        operations: tuple[str, ...],
    ) -> bool:
        return await self._vector_store.has_candidates(
            domains=tuple(domain.value for domain in domains),
            route_types=route_types,
            operations=operations,
        )

    @staticmethod
    def _metadata_routes(route_type: RouteType) -> tuple[str, ...]:
        if route_type is RouteType.TRANSACTION:
            return ("transaction",)
        if route_type in {RouteType.STRUCTURED_QUERY, RouteType.ANALYTICS}:
            return ("structured_query",)
        return ()

    @staticmethod
    def _metadata_operations(operation: Operation) -> tuple[str, ...]:
        if operation is Operation.READ or operation is Operation.NONE:
            return ("get", "list", "check")
        return (operation.value,)

    @staticmethod
    def _enforce_operation_invariant(
        operation: Operation,
        tools: tuple[object, ...],
    ) -> None:
        if operation is not Operation.READ:
            return
        invalid = [
            tool
            for tool in tools
            if getattr(tool, "query_operation", None) is not Operation.READ
        ]
        if invalid:
            raise RoutingInvariantError(
                "READ_QUERY_CONTAINS_WRITE_CANDIDATE"
            )

    @staticmethod
    def _validated_candidates(
        operation: Operation,
        candidates: list[ToolCandidate],
    ) -> list[ToolCandidate]:
        if operation is Operation.READ and any(
            candidate.operation is not Operation.READ
            for candidate in candidates
        ):
            raise RoutingInvariantError(
                "READ_QUERY_CONTAINS_WRITE_CANDIDATE"
            )
        return candidates
