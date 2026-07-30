from __future__ import annotations

import asyncio
import json
import sys
from datetime import date
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]
from pydantic import BaseModel, ConfigDict

from app.config import get_settings
from app.llm.client import build_llm_client
from app.persistence.database import Database
from app.retrieval.embeddings import OllamaEmbeddingProvider
from app.retrieval.vector_store import DatabasePgVectorStore
from app.routing.candidate_retriever import (
    CandidateRetrievalOutcome,
    CandidateRetriever,
)
from app.routing.intent_refiner import refine_read_intent
from app.routing.query_classifier import QueryClassifier, QueryClassifierError
from app.routing.query_normalizer import QueryNormalizer
from app.routing.schemas import (
    CandidateRetrievalRequest,
    Domain,
    QueryClassification,
    ToolSelectorRequest,
)
from app.routing.taxonomy import (
    Intent,
    Operation,
    QueryRoute,
    SubjectScope,
    SubjectType,
)
from app.routing.tool_selector import ToolSelector
from app.tools import build_tool_registry

DATASET = (
    Path(__file__).parents[1]
    / "tests"
    / "evaluation"
    / "data"
    / "routing_sync_cases.yaml"
)


class RoutingSyncCase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str
    expected_route: str
    expected_intent: str
    expected_operation: str
    expected_subject_type: str
    expected_tool: str


def subject_type(scope: str) -> SubjectType:
    return {
        "self": SubjectType.SELF,
        "named_employee": SubjectType.EMPLOYEE,
        "department": SubjectType.DEPARTMENT,
        "company": SubjectType.COMPANY,
        "general": SubjectType.GENERAL,
        "unknown": SubjectType.GENERAL,
        "direct_reports": SubjectType.EMPLOYEE,
    }[scope]


async def run() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    raw: list[dict[str, Any]] = yaml.safe_load(DATASET.read_text("utf-8"))
    cases = [RoutingSyncCase.model_validate(item) for item in raw]
    settings = get_settings()
    llm = build_llm_client(settings, purpose="classifier")
    embeddings = OllamaEmbeddingProvider(settings)
    database = Database(settings.database_url)
    registry = build_tool_registry()
    normalizer = QueryNormalizer()
    classifier = QueryClassifier(llm)
    retriever = CandidateRetriever(
        registry,
        embeddings,
        DatabasePgVectorStore(database),
    )
    selector = ToolSelector(llm, registry, settings)
    failed = 0
    provider_available = True
    try:
        for case in cases:
            normalized = normalizer.normalize(case.query)
            classification_source = "llm"
            if provider_available:
                try:
                    classification = await classifier.classify(normalized)
                except QueryClassifierError as error:
                    provider_available = False
                    classification_source = (
                        f"semantic_fallback_after_{error.reason_code}"
                    )
                    classification = _semantic_classification(
                        normalized.normalized_text
                    )
            else:
                classification_source = "semantic_fallback_provider_disabled"
                classification = _semantic_classification(
                    normalized.normalized_text
                )
            outcome: CandidateRetrievalOutcome = await retriever.retrieve(
                CandidateRetrievalRequest(
                    query=normalized.normalized_text,
                    classification=classification,
                    top_k=5,
                    fetch_k=20,
                    min_score=settings.tool_min_score,
                )
            )
            contexts = selector.build_candidate_contexts(outcome.candidates)
            selection = await selector.select(
                ToolSelectorRequest(
                    original_query=case.query,
                    normalized_query=normalized.normalized_text,
                    classification=classification,
                    candidates=contexts,
                    current_date=date(2026, 7, 30),
                    timezone="Asia/Ho_Chi_Minh",
                )
            )
            actual_subject = subject_type(
                classification.scope.value
            ).value
            selected_tool = selection.selected_tool
            source = (
                "direct_mapping"
                if selection.reason_code == "DIRECT_INTENT_MAPPING"
                else "selector"
                if contexts
                else "no_registered_tool"
            )
            row = {
                "query": case.query,
                "route": classification.route.value,
                "intent": (
                    classification.intent.value
                    if classification.intent
                    else None
                ),
                "operation": classification.operation.value,
                "subject_type": actual_subject,
                "selected_tool": selected_tool,
                "source": source,
                "classification_source": classification_source,
            }
            ok = (
                row["route"] == case.expected_route
                and row["intent"] == case.expected_intent
                and row["operation"] == case.expected_operation
                and row["subject_type"] == case.expected_subject_type
                and row["selected_tool"] == case.expected_tool
            )
            row["status"] = "pass" if ok else "fail"
            failed += int(not ok)
            print(json.dumps(row, ensure_ascii=False), flush=True)
    finally:
        await llm.close()
        await embeddings.close()
        await database.close()
    print(
        json.dumps(
            {
                "total": len(cases),
                "passed": len(cases) - failed,
                "failed": failed,
            }
        )
    )
    return 1 if failed else 0


def _semantic_classification(query: str) -> QueryClassification:
    seed = QueryClassification(
        route=QueryRoute.DATA_QUERY,
        domain=Domain.GENERAL,
        intent=Intent.ATTENDANCE_DAILY,
        operation=Operation.READ,
        scope=SubjectScope.SELF,
        confidence=0.6,
        reason_code="EVALUATION_SEMANTIC_SEED",
    )
    return refine_read_intent(query, seed)


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run()))
