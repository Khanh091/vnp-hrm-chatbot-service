import re
from time import perf_counter
from typing import Any

from langgraph.runtime import Runtime

from app.context.date_resolver import AmbiguousDateExpression
from app.orchestration.context import GraphContext
from app.orchestration.nodes.common import stage_update, trusted_today
from app.orchestration.state import ChatGraphState
from app.routing.schemas import ToolSelection
from app.tools.definitions import TrustedExecutionContext, ValidatedToolExecution


def _normalized(value: str) -> str:
    return " ".join(value.casefold().split())


def _leave_type_options(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, dict):
        for key in ("leave_types", "items", "data", "result"):
            nested = data.get(key)
            if isinstance(nested, list):
                data = nested
                break
    if not isinstance(data, list):
        return []
    options: list[dict[str, Any]] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        value = item.get("id") or item.get("value") or item.get("leave_type_id")
        label = item.get("name") or item.get("label") or item.get("display_name")
        if isinstance(value, int) and value > 0 and isinstance(label, str):
            options.append({"value": value, "label": label})
    return options


async def merge_clarification_node(
    state: ChatGraphState, runtime: Runtime[GraphContext]
) -> dict[str, object]:
    started = perf_counter()
    tool_name = state.get("pending_tool_name")
    if not tool_name:
        return {
            **stage_update(
                state,
                event="clarification_context_missing",
                timing_name="argument_merge_ms",
                started=started,
            ),
            "workflow_issues": [{"code": "CLARIFICATION_CONTEXT_MISSING"}],
            "pending_tool_name": None,
        }
    tool = runtime.context.tool_registry.get(tool_name)
    if not tool.enabled:
        return {
            **stage_update(
                state,
                event="pending_tool_disabled",
                timing_name="argument_merge_ms",
                started=started,
            ),
            "workflow_issues": [{"code": "PENDING_TOOL_DISABLED"}],
            "pending_tool_name": None,
        }
    workflow = runtime.context.workflow_registry.get(tool_name)
    missing = list(state.get("missing_arguments", []))
    ambiguous = list(state.get("ambiguous_arguments", []))
    field: str | None
    if workflow:
        field = workflow.next_field(missing, ambiguous)
    else:
        unresolved = ambiguous or missing
        field = unresolved[0] if unresolved else None
    message = (state.get("user_message") or "").strip()
    arguments = dict(state.get("collected_arguments", {}))
    options: list[dict[str, Any]] = []
    resolved = False
    trusted_data = state["trusted_context"]
    if field in {"date", "date_from", "date_to"}:
        try:
            value = runtime.context.date_resolver.resolve(
                message,
                current_date=trusted_today(str(trusted_data["timezone"])),
                timezone=str(trusted_data["timezone"]),
            )
        except AmbiguousDateExpression:
            value = None
        if value is not None:
            if field == "date" and value.date_from == value.date_to:
                arguments[field] = value.date_from
                resolved = True
            elif field in {"date_from", "date_to"}:
                arguments[field] = (
                    value.date_from if field == "date_from" else value.date_to
                )
                resolved = True
    elif field == "request_id":
        match = re.search(r"(?:LEAVE-)?(\d+)", message, re.IGNORECASE)
        if match:
            arguments[field] = int(match.group(1))
            resolved = True
    elif field == "leave_type_id":
        match = re.fullmatch(r"\s*(\d+)\s*", message)
        if match:
            arguments[field] = int(match.group(1))
            resolved = True
        else:
            lookup = await runtime.context.tool_executor.execute_validated(
                ValidatedToolExecution(
                    tool_name="leave_list_types",
                    arguments={},
                    trusted_context=TrustedExecutionContext.model_validate(
                        trusted_data
                    ),
                )
            )
            if lookup.success:
                options = _leave_type_options(lookup.data)
                matches = [
                    item
                    for item in options
                    if _normalized(str(item["label"])) == _normalized(message)
                ]
                if len(matches) == 1:
                    arguments[field] = matches[0]["value"]
                    resolved = True
    elif field:
        arguments[field] = message
        resolved = bool(message)

    if resolved and field:
        missing = [item for item in missing if item != field]
        ambiguous = [item for item in ambiguous if item != field]
    persisted_selection = state.get("workflow_data", {}).get("selection")
    selection = (
        ToolSelection.model_validate(persisted_selection)
        if persisted_selection
        else ToolSelection(
            selected_tool=tool_name,
            confidence=1,
            extracted_arguments={},
            reason_code="CLARIFICATION_RESUME",
        )
    )
    selection = selection.model_copy(
        update={
            "extracted_arguments": {},
            "missing_arguments": [],
            "ambiguous_arguments": [],
            "requires_clarification": False,
            "clarification_question": None,
        }
    )
    update = stage_update(
        state,
        event="clarification_merged",
        timing_name="argument_merge_ms",
        started=started,
        data={"field": field, "resolved": resolved},
    )
    update.update(
        {
            "selection": selection.model_dump(mode="json"),
            "collected_arguments": arguments,
            "missing_arguments": missing,
            "ambiguous_arguments": ambiguous,
            "workflow_data": {
                **state.get("workflow_data", {}),
                "clarification_options": options,
            },
        }
    )
    return update
