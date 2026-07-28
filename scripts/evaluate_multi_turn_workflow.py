from pathlib import Path
from statistics import mean
from time import perf_counter
from typing import Any

import yaml  # type: ignore[import-untyped]
from pydantic import BaseModel, ConfigDict, Field


class EvaluationTurn(BaseModel):
    model_config = ConfigDict(extra="allow")

    user: str | None = None
    action: str | None = None
    expected_type: str
    expected_field: str | None = None
    expected_tool: str | None = None
    expected_error: str | None = None
    forbidden_stages: list[str] = Field(default_factory=list)


class EvaluationCase(BaseModel):
    model_config = ConfigDict(extra="allow")

    name: str
    turns: list[EvaluationTurn]


def load_cases(path: Path) -> list[EvaluationCase]:
    payload: Any = yaml.safe_load(path.read_text(encoding="utf-8"))
    return [EvaluationCase.model_validate(item) for item in payload]


def main() -> int:
    path = Path("tests/evaluation/data/multi_turn_workflow_cases.yaml")
    started = perf_counter()
    cases = load_cases(path)
    latencies = [
        (perf_counter() - started) * 1000 / max(len(cases), 1)
        for _ in cases
    ]
    total_turns = sum(len(case.turns) for case in cases)
    clarification_turns = sum(
        1
        for case in cases
        for turn in case.turns
        if turn.expected_type == "clarification_required"
    )
    confirmation_turns = sum(
        1
        for case in cases
        for turn in case.turns
        if turn.action == "confirm"
    )
    print(f"Workflow cases: {len(cases)}")
    print(f"Total turns: {total_turns}")
    print(f"Clarification turns: {clarification_turns}")
    print(f"Confirmation turns: {confirmation_turns}")
    print(f"Dataset validation latency average: {mean(latencies):.3f} ms")
    print(
        "Execution accuracy: not measured by this schema-only command; "
        "run pytest integration workflow fixtures for mock-Odoo execution."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
