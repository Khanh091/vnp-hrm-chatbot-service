from __future__ import annotations

import asyncio
from pathlib import Path
from time import perf_counter
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict

from app.config import get_settings
from app.llm.client import OllamaLlmClient
from app.persistence.database import Database
from app.retrieval.embeddings import OllamaEmbeddingProvider
from app.retrieval.vector_store import DatabasePgVectorStore
from app.routing.candidate_retriever import CandidateRetriever
from app.routing.query_classifier import QueryClassifier
from app.routing.query_normalizer import QueryNormalizer
from app.routing.service import RoutingService
from app.tools import build_tool_registry

DATASET = Path(__file__).parents[1] / "tests/evaluation/data/routing_cases.yaml"


class EvaluationCase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str
    expected_route: str
    expected_domain: str
    expected_secondary_domain: str | None = None
    expected_scope: str | None = None
    expected_tool_in_top_k: str | None = None


def _percent(numerator: int, denominator: int) -> float:
    return 100.0 * numerator / denominator if denominator else 0.0


async def run() -> int:
    raw: list[dict[str, Any]] = yaml.safe_load(DATASET.read_text("utf-8"))
    cases = [EvaluationCase.model_validate(item) for item in raw]
    settings = get_settings()
    llm = OllamaLlmClient(settings)
    embeddings = OllamaEmbeddingProvider(settings)
    database = Database(settings.database_url)
    service = RoutingService(
        QueryNormalizer(),
        QueryClassifier(llm),
        CandidateRetriever(
            build_tool_registry(),
            embeddings,
            DatabasePgVectorStore(database),
        ),
        top_k=max(5, settings.tool_top_k),
        fetch_k=max(20, settings.tool_fetch_k),
        min_score=settings.tool_min_score,
    )

    route_correct = 0
    domain_correct = 0
    recall = {1: 0, 3: 0, 5: 0}
    retrieval_cases = 0
    latencies: list[float] = []
    failures: list[str] = []
    try:
        for case in cases:
            started = perf_counter()
            try:
                result = await service.route(case.query)
            except Exception as error:
                failures.append(f"{case.query} [{type(error).__name__}]")
                continue
            latencies.append((perf_counter() - started) * 1000)
            route_ok = (
                result.classification.route_type.value == case.expected_route
            )
            domain_ok = (
                result.classification.primary_domain.value
                == case.expected_domain
            )
            route_correct += int(route_ok)
            domain_correct += int(domain_ok)
            candidate_names = [
                candidate.tool_name for candidate in result.candidates
            ]
            recall_ok = True
            if case.expected_tool_in_top_k:
                retrieval_cases += 1
                for k in recall:
                    hit = case.expected_tool_in_top_k in candidate_names[:k]
                    recall[k] += int(hit)
                recall_ok = case.expected_tool_in_top_k in candidate_names[:5]
            if not route_ok or not domain_ok or not recall_ok:
                failures.append(
                    f"{case.query} [route={result.classification.route_type.value}, "
                    f"domain={result.classification.primary_domain.value}, "
                    f"top5={candidate_names[:5]}]"
                )
    finally:
        await llm.close()
        await embeddings.close()
        await database.close()

    sorted_latencies = sorted(latencies)
    p95_index = max(0, int(len(sorted_latencies) * 0.95 + 0.999) - 1)
    average = sum(latencies) / len(latencies) if latencies else 0.0
    p95 = sorted_latencies[p95_index] if sorted_latencies else 0.0
    print(f"Total cases: {len(cases)}")
    print(f"Route accuracy: {_percent(route_correct, len(cases)):.2f}%")
    print(f"Domain accuracy: {_percent(domain_correct, len(cases)):.2f}%")
    for k in (1, 3, 5):
        print(
            f"Candidate recall@{k}: "
            f"{_percent(recall[k], retrieval_cases):.2f}%"
        )
    print(f"Average latency: {average:.2f} ms")
    print(f"P95 latency: {p95:.2f} ms")
    print(f"Failed cases: {len(failures)}")
    for failure in failures:
        print(f"- {failure}")
    return 1 if failures else 0


def main() -> None:
    raise SystemExit(asyncio.run(run()))


if __name__ == "__main__":
    main()
