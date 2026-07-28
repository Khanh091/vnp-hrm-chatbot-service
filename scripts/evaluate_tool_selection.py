from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import date
from pathlib import Path
from time import perf_counter
from typing import Any

import yaml  # type: ignore[import-untyped]
from pydantic import BaseModel, ConfigDict, Field

from app.config import get_settings
from app.llm.client import build_llm_client
from app.persistence.database import Database
from app.retrieval.embeddings import OllamaEmbeddingProvider
from app.retrieval.vector_store import DatabasePgVectorStore
from app.routing.argument_resolver import ArgumentResolver
from app.routing.candidate_retriever import CandidateRetriever
from app.routing.query_classifier import QueryClassifier
from app.routing.query_normalizer import QueryNormalizer
from app.routing.schemas import ToolSelectorRequest
from app.routing.service import RoutingService
from app.routing.tool_selector import ToolSelector
from app.routing.validator import ToolSelectionValidator
from app.tools import build_tool_registry

DATASET = (
    Path(__file__).parents[1]
    / "tests/evaluation/data/tool_selection_cases.yaml"
)
EVALUATION_DATE = date(2026, 7, 27)
EVALUATION_TIMEZONE = "Asia/Ho_Chi_Minh"


class EvaluationCase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str
    expected_tool: str | None = None
    expected_arguments: dict[str, Any] = Field(default_factory=dict)
    expected_result_type: str


def _percent(numerator: int, denominator: int) -> float:
    return 100 * numerator / denominator if denominator else 0.0


async def run(*, limit: int | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    cases = [
        EvaluationCase.model_validate(item)
        for item in yaml.safe_load(DATASET.read_text("utf-8"))
    ]
    if limit is not None:
        cases = cases[:limit]
    settings = get_settings()
    llm = build_llm_client(settings)
    embeddings = OllamaEmbeddingProvider(settings)
    database = Database(settings.database_url)
    registry = build_tool_registry()
    selector = ToolSelector(llm, registry, settings)
    resolver = ArgumentResolver()
    validator = ToolSelectionValidator(registry, settings)
    routing = RoutingService(
        QueryNormalizer(),
        QueryClassifier(llm),
        CandidateRetriever(
            registry,
            embeddings,
            DatabasePgVectorStore(database),
        ),
        top_k=max(5, settings.tool_top_k),
        fetch_k=max(20, settings.tool_fetch_k),
        min_score=settings.tool_min_score,
    )
    tool_correct = 0
    argument_correct = 0
    result_type_correct = 0
    latencies: list[float] = []
    classification_latencies: list[float] = []
    selection_latencies: list[float] = []
    failures: list[str] = []
    try:
        for index, case in enumerate(cases, start=1):
            started = perf_counter()
            routed = await routing.route(case.query)
            classification_latencies.append(
                routed.timings.classification_ms
            )
            selected_tool: str | None = None
            arguments: dict[str, Any] = {}
            result_type = "unsupported"
            contexts = selector.build_candidate_contexts(routed.candidates)
            if contexts:
                selection_started = perf_counter()
                selection = await selector.select(
                    ToolSelectorRequest(
                        original_query=case.query,
                        normalized_query=routed.normalized_query,
                        classification=routed.classification,
                        candidates=contexts,
                        current_date=EVALUATION_DATE,
                        timezone=EVALUATION_TIMEZONE,
                    )
                )
                selection_latencies.append(
                    (perf_counter() - selection_started) * 1000
                )
                selected_tool = selection.selected_tool
                if selected_tool is not None:
                    tool = registry.get(selected_tool)
                    resolution = resolver.resolve(
                        selection,
                        tool,
                        query=routed.normalized_query,
                        current_date=EVALUATION_DATE,
                        timezone=EVALUATION_TIMEZONE,
                    )
                    validation = validator.validate(
                        selection,
                        resolution,
                        classification=routed.classification,
                        candidates=contexts,
                    )
                    arguments = validation.normalized_arguments
                    result_type = (
                        "clarification_required"
                        if validation.requires_clarification
                        else "confirmation_required"
                        if validation.requires_confirmation
                        else "answer"
                        if validation.can_execute
                        else "error"
                    )
            latency = (perf_counter() - started) * 1000
            latencies.append(latency)
            tool_ok = selected_tool == case.expected_tool
            arguments_json = {
                key: (
                    value.isoformat() if isinstance(value, date) else value
                )
                for key, value in arguments.items()
                if key != "idempotency_key"
            }
            args_ok = all(
                arguments_json.get(key) == value
                for key, value in case.expected_arguments.items()
            )
            type_ok = result_type == case.expected_result_type
            tool_correct += int(tool_ok)
            argument_correct += int(args_ok)
            result_type_correct += int(type_ok)
            if not (tool_ok and args_ok and type_ok):
                failures.append(
                    f"{case.query} [tool={selected_tool}, "
                    f"arguments={arguments_json}, type={result_type}]"
                )
            print(
                f"[{index}/{len(cases)}] tool={selected_tool} "
                f"type={result_type}",
                flush=True,
            )
    finally:
        await llm.close()
        await embeddings.close()
        await database.close()

    ordered = sorted(latencies)
    p95_index = max(0, int(len(ordered) * 0.95 + 0.999) - 1)
    average = sum(latencies) / len(latencies) if latencies else 0.0
    classification_average = (
        sum(classification_latencies) / len(classification_latencies)
        if classification_latencies
        else 0.0
    )
    selection_average = (
        sum(selection_latencies) / len(selection_latencies)
        if selection_latencies
        else 0.0
    )
    p95 = ordered[p95_index] if ordered else 0.0
    print(f"Total cases: {len(cases)}")
    print(
        f"Tool selection accuracy: "
        f"{_percent(tool_correct, len(cases)):.2f}%"
    )
    print(
        f"Argument extraction accuracy: "
        f"{_percent(argument_correct, len(cases)):.2f}%"
    )
    print(
        f"Result type accuracy: "
        f"{_percent(result_type_correct, len(cases)):.2f}%"
    )
    print(f"Average latency: {average:.2f} ms")
    print(f"P95 latency: {p95:.2f} ms")
    print(
        f"Average classification latency: "
        f"{classification_average:.2f} ms"
    )
    print(f"Average tool selection latency: {selection_average:.2f} ms")
    print(f"Failed cases: {len(failures)}")
    for failure in failures:
        print(f"- {failure}")
    return 1 if failures else 0


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None)
    arguments = parser.parse_args()
    if arguments.limit is not None and arguments.limit <= 0:
        parser.error("--limit must be greater than zero")
    raise SystemExit(asyncio.run(run(limit=arguments.limit)))


if __name__ == "__main__":
    main()
