import pytest

from app.persistence.repositories.tool_embedding_repository import (
    VectorSearchMatch,
)
from app.routing.candidate_retriever import CandidateRetriever
from app.routing.schemas import (
    CandidateRetrievalRequest,
    Domain,
    QueryClassification,
    RouteType,
    SubjectScope,
)
from app.tools import build_tool_registry


class FakeEmbeddings:
    dimension = 2

    def __init__(self) -> None:
        self.query_calls = 0
        self.last_query = ""

    async def embed_query(self, text: str) -> list[float]:
        self.query_calls += 1
        self.last_query = text
        return [0.1, 0.2]

    async def embed_documents(
        self,
        texts: list[str],
    ) -> list[list[float]]:
        return [[0.1, 0.2] for _ in texts]


class FakeVectorStore:
    def __init__(
        self,
        matches: list[VectorSearchMatch],
        *,
        available_domains: set[str] | None = None,
    ) -> None:
        self.matches = matches
        self.available_domains = available_domains or {"leave"}
        self.has_calls: list[
            tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]
        ] = []
        self.search_calls: list[
            tuple[
                tuple[str, ...],
                tuple[str, ...],
                tuple[str, ...],
                int,
            ]
        ] = []

    async def has_candidates(
        self,
        *,
        domains: tuple[str, ...],
        route_types: tuple[str, ...],
        operations: tuple[str, ...],
    ) -> bool:
        self.has_calls.append((domains, route_types, operations))
        return bool(set(domains) & self.available_domains)

    async def search(
        self,
        *,
        embedding: list[float],
        domains: tuple[str, ...],
        route_types: tuple[str, ...],
        operations: tuple[str, ...],
        limit: int,
    ) -> list[VectorSearchMatch]:
        self.search_calls.append((domains, route_types, operations, limit))
        return self.matches


def match(
    tool_name: str,
    score: float,
    *,
    domain: str = "leave",
    operation: str = "get",
) -> VectorSearchMatch:
    return VectorSearchMatch(
        tool_name=tool_name,
        domain=domain,
        capability="ignored.database.capability",
        operation=operation,
        score=score,
    )


def request(
    *,
    domain: Domain = Domain.LEAVE,
    route: RouteType = RouteType.STRUCTURED_QUERY,
    confidence: float = 0.9,
    secondary: list[Domain] | None = None,
    top_k: int = 5,
    min_score: float = 0.45,
    scope: SubjectScope = SubjectScope.SELF,
) -> CandidateRetrievalRequest:
    return CandidateRetrievalRequest(
        query="Tôi còn bao nhiêu ngày phép?",
        classification=QueryClassification(
            route_type=route,
            primary_domain=domain,
            secondary_domains=secondary or [],
            scope=scope,
            confidence=confidence,
        ),
        top_k=top_k,
        fetch_k=20,
        min_score=min_score,
    )


@pytest.mark.asyncio
async def test_retriever_filters_domain_and_route_before_search() -> None:
    store = FakeVectorStore([match("leave_get_balance", 0.9)])

    outcome = await CandidateRetriever(
        build_tool_registry(), FakeEmbeddings(), store
    ).retrieve(request())

    assert outcome.candidates[0].tool_name == "leave_get_balance"
    assert store.has_calls == [
        (("leave",), ("structured_query",), ("get", "list", "check"))
    ]
    assert store.search_calls == [
        (("leave",), ("structured_query",), ("get", "list", "check"), 20)
    ]


@pytest.mark.asyncio
async def test_retriever_embeds_normalized_query_once() -> None:
    store = FakeVectorStore([match("leave_get_balance", 0.9)])
    embeddings = FakeEmbeddings()

    await CandidateRetriever(
        build_tool_registry(), embeddings, store
    ).retrieve(request())

    assert embeddings.query_calls == 1
    assert embeddings.last_query == "Tôi còn bao nhiêu ngày phép?"


@pytest.mark.asyncio
async def test_retriever_uses_transaction_route_filter() -> None:
    store = FakeVectorStore(
        [match("leave_create_request", 0.9, operation="create")]
    )

    outcome = await CandidateRetriever(
        build_tool_registry(), FakeEmbeddings(), store
    ).retrieve(request(route=RouteType.TRANSACTION))

    assert outcome.candidates[0].tool_name == "leave_create_request"
    assert store.search_calls[0][1] == ("transaction",)


@pytest.mark.asyncio
async def test_retriever_applies_score_threshold_sort_and_top_k() -> None:
    store = FakeVectorStore(
        [
            match("leave_get_history", 0.7, operation="list"),
            match("leave_get_used", 0.95),
            match("leave_get_balance", 0.4),
        ]
    )

    outcome = await CandidateRetriever(
        build_tool_registry(), FakeEmbeddings(), store
    ).retrieve(request(top_k=1, min_score=0.5))

    assert [item.tool_name for item in outcome.candidates] == ["leave_get_used"]
    assert outcome.candidates[0].rank == 1


@pytest.mark.asyncio
async def test_retriever_drops_tool_missing_from_runtime_registry() -> None:
    store = FakeVectorStore(
        [
            match("database_only_tool", 0.99),
            match("leave_get_balance", 0.9),
        ]
    )

    outcome = await CandidateRetriever(
        build_tool_registry(), FakeEmbeddings(), store
    ).retrieve(request())

    assert [item.tool_name for item in outcome.candidates] == [
        "leave_get_balance"
    ]


@pytest.mark.asyncio
async def test_retriever_falls_back_to_secondary_domain() -> None:
    store = FakeVectorStore(
        [match("leave_get_balance", 0.9)],
        available_domains={"leave"},
    )

    outcome = await CandidateRetriever(
        build_tool_registry(), FakeEmbeddings(), store
    ).retrieve(
        request(
            domain=Domain.ATTENDANCE,
            secondary=[Domain.LEAVE],
        )
    )

    assert outcome.fallback_reason == "SECONDARY_DOMAIN_FALLBACK"
    assert store.search_calls[0][0] == ("leave",)


@pytest.mark.asyncio
async def test_low_confidence_can_expand_to_small_supported_domain_set() -> None:
    store = FakeVectorStore(
        [match("leave_get_balance", 0.9)],
        available_domains={"leave"},
    )

    outcome = await CandidateRetriever(
        build_tool_registry(), FakeEmbeddings(), store
    ).retrieve(
        request(domain=Domain.GENERAL, confidence=0.4)
    )

    assert outcome.fallback_reason == "LOW_CONFIDENCE_DOMAIN_EXPANSION"
    assert set(store.search_calls[0][0]) == {
        "profile",
        "attendance",
        "leave",
    }


@pytest.mark.asyncio
async def test_unclear_transaction_never_broadens() -> None:
    store = FakeVectorStore(
        [match("leave_create_request", 0.9, operation="create")],
        available_domains={"leave"},
    )
    embeddings = FakeEmbeddings()

    outcome = await CandidateRetriever(
        build_tool_registry(), embeddings, store
    ).retrieve(
        request(
            domain=Domain.GENERAL,
            route=RouteType.TRANSACTION,
            confidence=0.4,
        )
    )

    assert outcome.candidates == []
    assert outcome.fallback_reason == "TRANSACTION_DOMAIN_UNCLEAR"
    assert embeddings.query_calls == 0
    assert store.search_calls == []


@pytest.mark.asyncio
async def test_retriever_enforces_runtime_supported_scope() -> None:
    store = FakeVectorStore([match("leave_get_balance", 0.9)])

    outcome = await CandidateRetriever(
        build_tool_registry(), FakeEmbeddings(), store
    ).retrieve(request(scope=SubjectScope.NAMED_EMPLOYEE))

    assert outcome.candidates == []
