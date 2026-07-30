import re
from time import perf_counter
from typing import Any

from langgraph.runtime import Runtime

from app.context.date_resolver import AmbiguousDateExpression
from app.context.entity_resolver import EntityOption
from app.orchestration.context import GraphContext
from app.orchestration.nodes.common import stage_update, trusted_today
from app.orchestration.state import ChatGraphState, ChatResponseType, WorkflowStatus
from app.routing.schemas import ToolSelection
from app.tools.definitions import TrustedExecutionContext, ValidatedToolExecution
from app.workflows.slot_manager import SlotState


def merge_workflow_metadata(
    current: dict[str, Any],
    *,
    options: list[dict[str, Any]],
    slot_issues: list[dict[str, Any]],
) -> dict[str, Any]:
    updated = {**current, "slot_issues": slot_issues}
    if options:
        updated["clarification_options"] = options
    return updated


async def merge_clarification_node(
    state: ChatGraphState, runtime: Runtime[GraphContext]
) -> dict[str, object]:
    started = perf_counter()
    tool_name = state.get("pending_tool_name")
    if not tool_name:
        await runtime.context.conversation_service.clear_workflow(
            state["conversation_id"],
            int(state["trusted_context"]["odoo_user_id"]),
        )
        return {
            **stage_update(
                state,
                event="clarification_context_missing",
                timing_name="argument_merge_ms",
                started=started,
            ),
            "workflow_issues": [{"code": "CLARIFICATION_CONTEXT_MISSING"}],
            "pending_tool_name": None,
            "workflow_status": WorkflowStatus.FAILED,
            "response_type": ChatResponseType.ERROR,
            "response_text": "Ngữ cảnh làm rõ không còn hợp lệ.",
            "response_data": {
                "reason_code": "CLARIFICATION_CONTEXT_MISSING"
            },
        }
    tool = runtime.context.tool_registry.get(tool_name)
    if not tool.enabled:
        await runtime.context.conversation_service.clear_workflow(
            state["conversation_id"],
            int(state["trusted_context"]["odoo_user_id"]),
        )
        return {
            **stage_update(
                state,
                event="pending_tool_disabled",
                timing_name="argument_merge_ms",
                started=started,
            ),
            "workflow_issues": [{"code": "PENDING_TOOL_DISABLED"}],
            "pending_tool_name": None,
            "workflow_status": WorkflowStatus.FAILED,
            "response_type": ChatResponseType.ERROR,
            "response_text": "Nghiệp vụ đang chờ hiện không còn khả dụng.",
            "response_data": {"reason_code": "PENDING_TOOL_DISABLED"},
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
    options: list[dict[str, object]] = []
    resolved = False
    trusted_data = state["trusted_context"]
    structured = state.get("clarification")
    if (
        field
        and isinstance(structured, dict)
        and structured.get("field") == field
        and isinstance(structured.get("value"), (bool, float, int, str))
    ):
        structured_value = structured["value"]
        if field == "leave_type_id":
            known_options = [
                EntityOption.model_validate(item)
                for item in state.get("workflow_data", {}).get(
                    "clarification_options",
                    [],
                )
            ]
            if isinstance(structured_value, int) and any(
                option.value == structured_value
                for option in known_options
            ):
                arguments[field] = structured_value
                options = [
                    item.model_dump(mode="json") for item in known_options
                ]
                resolved = True
        elif field in {"employee_id", "department_id"}:
            subject_options = [
                item
                for item in state.get("workflow_data", {}).get(
                    "clarification_options",
                    [],
                )
                if isinstance(item, dict)
            ]
            if isinstance(structured_value, int) and any(
                item.get("value") == structured_value
                for item in subject_options
            ):
                arguments[field] = structured_value
                options = subject_options
                resolved = True
        else:
            arguments[field] = structured_value
            resolved = True
    elif field in {"date", "date_from", "date_to"}:
        try:
            value = runtime.context.date_resolver.resolve(
                message,
                current_date=trusted_today(str(trusted_data["timezone"])),
                timezone=str(trusted_data["timezone"]),
            )
        except AmbiguousDateExpression:
            value = None
            if field:
                ambiguous.append(field)
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
        typed_options = [
            EntityOption.model_validate(item)
            for item in state.get("workflow_data", {}).get(
                "clarification_options",
                [],
            )
        ]
        if not typed_options:
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
                typed_options = (
                    runtime.context.business_entity_resolver.leave_type_options(
                        lookup.data
                    )
                )
        options = [
            item.model_dump(mode="json") for item in typed_options
        ]
        numeric = re.fullmatch(r"\s*(\d+)\s*", message)
        matched = (
            next(
                (
                    option
                    for option in typed_options
                    if numeric and option.value == int(numeric.group(1))
                ),
                None,
            )
            if numeric
            else (
                runtime.context.business_entity_resolver.match_leave_type(
                    message,
                    typed_options,
                )
            )
        )
        if matched is not None:
            arguments[field] = matched.value
            resolved = True
    elif field:
        arguments[field] = message
        resolved = bool(message)

    if resolved and field:
        missing = [item for item in missing if item != field]
        ambiguous = [item for item in ambiguous if item != field]
    slot_issues: list[dict[str, Any]] = []
    if workflow:
        slot_state = runtime.context.slot_manager.merge(
            workflow,
            SlotState(
                values=state.get("collected_arguments", {}),
                missing=missing,
                ambiguous=ambiguous,
            ),
            arguments,
        )
        arguments = slot_state.values
        missing = runtime.context.slot_manager.get_missing_slots(
            workflow,
            slot_state,
        )
        ambiguous = slot_state.ambiguous
        slot_issues = [
            issue.model_dump(mode="json") for issue in slot_state.issues
        ]
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
    updated_workflow_data = merge_workflow_metadata(
        state.get("workflow_data", {}),
        options=options,
        slot_issues=slot_issues,
    )
    update.update(
        {
            "classification": updated_workflow_data.get(
                "classification", state.get("classification", {})
            ),
            "candidate_contexts": updated_workflow_data.get(
                "candidate_contexts", state.get("candidate_contexts", [])
            ),
            "selection": selection.model_dump(mode="json"),
            "collected_arguments": arguments,
            "missing_arguments": missing,
            "ambiguous_arguments": ambiguous,
            "workflow_data": updated_workflow_data,
        }
    )
    return update
