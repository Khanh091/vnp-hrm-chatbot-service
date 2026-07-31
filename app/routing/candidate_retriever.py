import logging
import re
from time import perf_counter

from pydantic import BaseModel, ConfigDict, Field

from app.retrieval.embeddings import EmbeddingProvider
from app.retrieval.tool_indexer import retrieval_route
from app.retrieval.vector_store import VectorStore
from app.routing.capabilities import (
    CapabilityResolver,
    NoToolForCapabilityError,
    RoutingResolutionError,
    ToolResolver,
)
from app.routing.schemas import (
    CandidateRetrievalRequest,
    Domain,
    Operation,
    RouteType,
    ToolCandidate,
)
from app.routing.taxonomy import SubjectScope, SubjectType
from app.tools.definitions import ToolDefinition
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
        self._capability_resolver = CapabilityResolver()
        self._tool_resolver = ToolResolver(registry)
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
        direct_matches: tuple[ToolDefinition, ...] = ()
        if classification.intent is not None:
            subject_type = self._subject_type(classification.scope)
            try:
                capabilities = self._capability_resolver.resolve(
                    intent=classification.intent,
                    subject_type=subject_type,
                )
                resolved_tools = []
                missing_tool = False
                for capability in capabilities:
                    try:
                        resolved_tools.extend(
                            self._tool_resolver.resolve(
                                capability=capability,
                                subject_type=subject_type,
                            )
                        )
                    except NoToolForCapabilityError:
                        missing_tool = True
                unique_tools = {
                    tool.name: tool for tool in resolved_tools
                }.values()
                direct_matches = tuple(
                    tool
                    for tool in unique_tools
                    if tool.supports_intent(classification.intent)
                    and (
                        classification.domain is None
                        or tool.domain.value == classification.domain.value
                    )
                    and tool.route is classification.route
                    and (
                        classification.operation is Operation.NONE
                        or tool.query_operation is classification.operation
                    )
                )
                if not direct_matches and missing_tool:
                    return CandidateRetrievalOutcome(
                        candidates=[],
                        embedding_ms=0,
                        vector_search_ms=0,
                        fallback_reason="NO_TOOL_FOR_CAPABILITY",
                    )
                if not direct_matches:
                    return CandidateRetrievalOutcome(
                        candidates=[],
                        embedding_ms=0,
                        vector_search_ms=0,
                        fallback_reason="NO_SUBJECT_COMPATIBLE_TOOL",
                    )
            except RoutingResolutionError as error:
                return CandidateRetrievalOutcome(
                    candidates=[],
                    embedding_ms=0,
                    vector_search_ms=0,
                    fallback_reason=error.reason_code,
                )
        if (
            classification.intent is not None
            and classification.intent.value == "leave.request_status"
            and direct_matches
        ):
            has_reference = bool(
                re.search(
                    r"\b(?:LEAVE[-\s]?\d+|"
                    r"(?:đơn|yêu cầu)(?:\s+nghỉ)?\s*(?:mã|số)?\s*\d+|"
                    r"gần nhất|mới nhất|đầu tiên|cuối cùng|trước đó)\b",
                    request.query,
                    re.IGNORECASE,
                )
            )
            has_reference = has_reference or bool(
                re.search(
                    r"\bđơn(?:\s+nghỉ)?\s+"
                    r"(?:thứ\s+(?:\d+|hai|ba|tư|bốn|năm|sáu|bảy|tám|chín|mười)"
                    r"|ngày\s+\d{1,2}[/-]\d{1,2}(?:[/-]\d{4})?)\b",
                    request.query,
                    re.IGNORECASE,
                )
            )
            preferred_name = (
                "leave_get_request_status"
                if has_reference
                else "leave_get_history"
            )
            direct_matches = tuple(
                tool
                for tool in direct_matches
                if tool.name == preferred_name
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
                        capability=tool.capability_name,
                        operation=tool.query_operation,
                        score=1.0,
                        rank=1,
                    )
                ],
                embedding_ms=0,
                vector_search_ms=0,
                fallback_reason="DIRECT_CAPABILITY_MAPPING",
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
                    and not tool.supports_intent(classification.intent)
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
                    capability=tool.capability_name,
                    operation=tool.query_operation,
                    score=match.score,
                    rank=len(candidates) + 1,
                )
            )
            if len(candidates) == request.top_k:
                break

        validated_candidates = self._validated_candidates(
            classification.operation,
            candidates,
        )
        return CandidateRetrievalOutcome(
            candidates=validated_candidates,
            embedding_ms=embedding_ms,
            vector_search_ms=vector_search_ms,
            fallback_reason=(
                fallback_reason
                if validated_candidates
                else "NO_RETRIEVAL_CANDIDATES"
            ),
        )

    @staticmethod
    def _subject_type(scope: SubjectScope) -> SubjectType:
        return {
            SubjectScope.SELF: SubjectType.SELF,
            SubjectScope.NAMED_EMPLOYEE: SubjectType.EMPLOYEE,
            SubjectScope.DEPARTMENT: SubjectType.DEPARTMENT,
            SubjectScope.COMPANY: SubjectType.COMPANY,
            SubjectScope.GENERAL: SubjectType.GENERAL,
            SubjectScope.UNKNOWN: SubjectType.GENERAL,
            SubjectScope.DIRECT_REPORTS: SubjectType.EMPLOYEE,
        }[scope]

    async def _select_domains(
        self,
        request: CandidateRetrievalRequest,
        route_types: tuple[str, ...],
        operations: tuple[str, ...],
    ) -> tuple[tuple[Domain, ...], str | None]:
        classification = request.classification
        supported_domains = self._domains_for_scope(
            classification.scope.value
        )
        primary = classification.primary_domain
        if primary in supported_domains and await self._has(
            (primary,),
            route_types,
            operations,
        ):
            return (primary,), None

        secondary = tuple(
            domain
            for domain in classification.secondary_domains
            if domain in supported_domains and domain is not primary
        )
        if secondary and await self._has(secondary, route_types, operations):
            return secondary, "SECONDARY_DOMAIN_FALLBACK"

        if classification.confidence >= _HIGH_CONFIDENCE:
            return (), "HIGH_CONFIDENCE_FILTER_EMPTY"
        if classification.route_type is RouteType.TRANSACTION:
            return (), "TRANSACTION_DOMAIN_UNCLEAR"

        broader = tuple(
            domain
            for domain in supported_domains
            if domain is not primary and domain not in secondary
        )
        if broader and await self._has(broader, route_types, operations):
            return broader, "LOW_CONFIDENCE_DOMAIN_EXPANSION"
        return (), "NO_METADATA_CANDIDATES"

    def _domains_for_scope(self, scope: str) -> tuple[Domain, ...]:
        subject_type = "employee" if scope == "named_employee" else scope
        return tuple(
            domain
            for domain in self._supported_domains
            if any(
                tool.enabled
                and tool.domain.value == domain.value
                and any(
                    item.value == subject_type
                    for item in tool.supported_subject_types
                )
                for tool in self._registry.list_all()
            )
        )

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
