from typing import Any

import pytest

from app.routing.candidate_retriever import CandidateRetriever
from app.routing.schemas import (
    CandidateRetrievalRequest,
    Domain,
    QueryClassification,
    ToolSelectorRequest,
)
from app.routing.taxonomy import Intent, Operation, QueryRoute, SubjectScope
from app.routing.tool_selector import ToolSelector
from app.tools import build_tool_registry


class NeverEmbed:
    dimension = 2

    async def embed_query(self, text: str) -> list[float]:
        raise AssertionError("direct intent mapping must not embed")

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        raise AssertionError("not used")


class NeverSearch:
    async def has_candidates(self, **kwargs: Any) -> bool:
        raise AssertionError("direct intent mapping must not query pgvector")

    async def search(self, **kwargs: Any) -> list[Any]:
        raise AssertionError("direct intent mapping must not query pgvector")


class NeverSelectWithLlm:
    calls = 0

    async def complete_structured(self, **kwargs: Any) -> Any:
        self.calls += 1
        raise AssertionError("single intent mapping must not call selector LLM")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("query", "domain", "intent", "tool_name"),
    [
        (
            "tên của tôi là gì",
            Domain.PROFILE,
            Intent.PROFILE_SUMMARY,
            "profile_get_summary",
        ),
        (
            "phòng ban của tôi là gì",
            Domain.PROFILE,
            Intent.PROFILE_EMPLOYMENT,
            "profile_get_employment",
        ),
        (
            "trình độ học vấn của tôi",
            Domain.PROFILE,
            Intent.PROFILE_EDUCATION,
            "profile_get_education",
        ),
        (
            "tôi còn bao nhiêu ngày phép",
            Domain.LEAVE,
            Intent.LEAVE_BALANCE,
            "leave_get_balance",
        ),
        (
            "số ngày đi muộn của tôi",
            Domain.ATTENDANCE,
            Intent.ATTENDANCE_LATE_SUMMARY,
            "attendance_get_late_summary",
        ),
    ],
)
async def test_single_intent_maps_without_embedding_or_selector_llm(
    query: str,
    domain: Domain,
    intent: Intent,
    tool_name: str,
) -> None:
    registry = build_tool_registry()
    classification = QueryClassification(
        route=QueryRoute.DATA_QUERY,
        domain=domain,
        intent=intent,
        operation=Operation.READ,
        scope=SubjectScope.SELF,
        confidence=0.96,
        reason_code="REGRESSION_CASE",
    )
    outcome = await CandidateRetriever(
        registry,
        NeverEmbed(),
        NeverSearch(),  # type: ignore[arg-type]
    ).retrieve(
        CandidateRetrievalRequest(
            query=query,
            classification=classification,
            top_k=3,
            fetch_k=10,
            min_score=0.45,
        )
    )
    llm = NeverSelectWithLlm()
    selector = ToolSelector(llm, registry)
    selection = await selector.select(
        request=ToolSelectorRequest(
            original_query=query,
            normalized_query=query,
            classification=classification,
            candidates=selector.build_candidate_contexts(outcome.candidates),
            current_date="2026-07-29",
            timezone="Asia/Ho_Chi_Minh",
        )
    )

    assert outcome.fallback_reason == "DIRECT_CAPABILITY_MAPPING"
    assert outcome.embedding_ms == 0
    assert outcome.candidates[0].tool_name == tool_name
    assert outcome.candidates[0].operation is Operation.READ
    assert selection.selected_tool == tool_name
    assert selection.scope is SubjectScope.SELF
    assert selection.extracted_arguments == {}
    assert llm.calls == 0
