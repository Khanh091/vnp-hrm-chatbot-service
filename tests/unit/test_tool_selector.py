from typing import Any

import pytest

from app.llm.client import LlmTimeoutError
from app.llm.structured_output import StructuredOutputError
from app.routing.schemas import (
    Domain,
    Operation,
    QueryClassification,
    RouteType,
    ToolCandidate,
    ToolSelection,
    ToolSelectorRequest,
)
from app.routing.tool_selector import ToolSelector, ToolSelectorError
from app.tools import build_tool_registry


class FakeClient:
    def __init__(self, result: ToolSelection | Exception) -> None:
        self.result = result
        self.calls = 0

    async def complete_structured(self, **kwargs: Any) -> ToolSelection:
        self.calls += 1
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def request_for(
    selector: ToolSelector,
    names: list[str],
) -> ToolSelectorRequest:
    registry = build_tool_registry()
    candidates = [
        ToolCandidate(
            tool_name=name,
            domain=Domain(registry.get(name).domain.value),
            capability=registry.get(name).capability,
            operation=Operation(registry.get(name).operation.value),
            score=0.9 - index * 0.05,
            rank=index + 1,
        )
        for index, name in enumerate(names)
    ]
    return ToolSelectorRequest(
        original_query="Tôi còn bao nhiêu ngày phép?",
        normalized_query="Tôi còn bao nhiêu ngày phép?",
        classification=QueryClassification(
            route_type=RouteType.STRUCTURED_QUERY,
            primary_domain=Domain.LEAVE,
            operation_hint=Operation.GET,
            confidence=0.95,
        ),
        candidates=selector.build_candidate_contexts(candidates),
        current_date="2026-07-27",
        timezone="Asia/Ho_Chi_Minh",
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "tool_name",
    [
        "leave_get_balance",
        "leave_get_used",
        "leave_get_history",
        "leave_get_request_status",
        "attendance_get_daily",
        "attendance_get_late_summary",
        "profile_get_summary",
    ],
)
async def test_selector_accepts_candidate_tool(tool_name: str) -> None:
    registry = build_tool_registry()
    client = FakeClient(
        ToolSelection(
            selected_tool=tool_name,
            confidence=0.95,
            reason_code="MATCHED_CANDIDATE",
        )
    )
    selector = ToolSelector(client, registry)

    result = await selector.select(request_for(selector, [tool_name]))

    assert result.selected_tool == tool_name
    assert client.calls == 1


@pytest.mark.asyncio
async def test_selector_rejects_tool_outside_candidates() -> None:
    registry = build_tool_registry()
    selector = ToolSelector(
        FakeClient(
            ToolSelection(
                selected_tool="leave_get_used",
                confidence=0.99,
                reason_code="OUTSIDE",
            )
        ),
        registry,
    )

    with pytest.raises(ToolSelectorError, match="outside"):
        await selector.select(request_for(selector, ["leave_get_balance"]))


@pytest.mark.asyncio
async def test_selector_allows_none_for_no_match() -> None:
    registry = build_tool_registry()
    selector = ToolSelector(
        FakeClient(
            ToolSelection(
                selected_tool=None,
                confidence=0.9,
                reason_code="NO_MATCH",
            )
        ),
        registry,
    )

    result = await selector.select(request_for(selector, ["leave_get_balance"]))

    assert result.selected_tool is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error",
    [
        StructuredOutputError("bad"),
        LlmTimeoutError("timeout"),
    ],
)
async def test_selector_wraps_llm_errors(error: Exception) -> None:
    registry = build_tool_registry()
    selector = ToolSelector(FakeClient(error), registry)

    with pytest.raises(ToolSelectorError):
        await selector.select(request_for(selector, ["leave_get_balance"]))


@pytest.mark.asyncio
async def test_selector_rejects_trusted_context_arguments() -> None:
    registry = build_tool_registry()
    selector = ToolSelector(
        FakeClient(
            ToolSelection(
                selected_tool="leave_get_balance",
                confidence=0.95,
                extracted_arguments={"odoo_user_id": 999},
                reason_code="UNSAFE",
            )
        ),
        registry,
    )

    with pytest.raises(ToolSelectorError, match="trusted"):
        await selector.select(request_for(selector, ["leave_get_balance"]))
