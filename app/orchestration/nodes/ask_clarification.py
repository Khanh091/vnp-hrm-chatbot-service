from time import perf_counter

from langgraph.runtime import Runtime

from app.context.conversation import ConversationStatus
from app.orchestration.context import GraphContext
from app.orchestration.nodes.common import stage_update, trusted_today
from app.orchestration.state import ChatGraphState, ChatResponseType
from app.tools.definitions import (
    TrustedExecutionContext,
    ValidatedToolExecution,
)
from app.workflows.clarification_policy import clarification_question
from app.workflows.leave_action import CHANGE_FIELD_OPTIONS


async def ask_clarification_node(
    state: ChatGraphState, runtime: Runtime[GraphContext]
) -> dict[str, object]:
    started = perf_counter()
    tool_name = state["pending_tool_name"]
    assert tool_name is not None
    workflow = runtime.context.workflow_registry.get(tool_name)
    missing = state.get("missing_arguments", [])
    ambiguous = state.get("ambiguous_arguments", [])
    if workflow:
        slot_state = runtime.context.slot_manager.initialize(
            workflow,
            state.get("collected_arguments", {}),
        ).model_copy(update={"ambiguous": ambiguous})
        field = state.get("workflow_data", {}).get("current_field") or (
            runtime.context.slot_manager.get_next_slot(workflow, slot_state)
        )
        slot = workflow.slot(field) if field else None
        question = slot.prompt if slot else clarification_question(field or "details")
        if field == "changes_instruction":
            question = "Bạn muốn thay đổi những thông tin nào và thành giá trị gì?"
        if field in ambiguous and field in {"date", "date_from", "date_to"}:
            question = "Bạn muốn chọn ngày nào và thuộc tuần nào?"
    else:
        field = (ambiguous or missing or ["details"])[0]
        question = clarification_question(field)
    conversation = await runtime.context.conversation_service.load_owned(
        state["conversation_id"],
        int(state["trusted_context"]["odoo_user_id"]),
    )
    workflow_data = {
        **state.get("workflow_data", {}),
        "classification": state.get("classification")
        or state.get("workflow_data", {}).get("classification"),
        "candidate_contexts": state.get("candidate_contexts")
        or state.get("workflow_data", {}).get("candidate_contexts", []),
        "selection": state.get("selection")
        or state.get("workflow_data", {}).get("selection"),
        "original_query": state.get("workflow_data", {}).get("original_query")
        or state.get("user_message"),
        "current_field": field,
    }
    if field == "changes":
        question = "Bạn muốn sửa thông tin nào?"
        workflow_data["clarification_options"] = [
            dict(item) for item in CHANGE_FIELD_OPTIONS
        ]
    if field == "leave_type_id" and not workflow_data.get("clarification_options"):
        lookup = await runtime.context.tool_executor.execute_validated(
            ValidatedToolExecution(
                tool_name="leave_get_types",
                arguments={},
                trusted_context=TrustedExecutionContext.model_validate(
                    state["trusted_context"]
                ),
            )
        )
        if lookup.success:
            workflow_data["clarification_options"] = [
                {
                    **option.model_dump(mode="json"),
                    "value": str(option.value),
                }
                for option in (
                    runtime.context.business_entity_resolver.leave_type_options(
                        lookup.data
                    )
                )
            ]
    options = workflow_data.get("clarification_options")
    if field == "request_id" and options:
        question = (
            "Bạn muốn sửa đơn nghỉ nào?"
            if tool_name == "leave_update_request"
            else "Bạn muốn hủy đơn nghỉ nào?"
        )
        if len(options) == 1:
            label = str(options[0].get("label") or "đơn nghỉ này")
            verb = "sửa" if tool_name == "leave_update_request" else "hủy"
            question = f"Bạn muốn {verb} đơn nghỉ {label}, đúng không?"
    date_fields = {
        "date",
        "date_from",
        "date_to",
        "start_date",
        "end_date",
        "valid_on",
    }
    external_slot = "leave_request_id" if field == "request_id" else field
    input_type = (
        "date"
        if field in date_fields
        else "entity_select"
        if field == "request_id" and options
        else "single_select"
        if options
        else "text"
    )
    clarification: dict[str, object] = {
        "input_type": input_type,
        "slot_name": external_slot,
    }
    if options:
        clarification["options"] = [
            {
                "value": str(item.get("value")),
                "label": str(item.get("label") or ""),
                **(
                    {"description": str(item.get("description"))}
                    if item.get("description")
                    else {}
                ),
            }
            for item in options
            if isinstance(item, dict)
        ]
    if input_type == "date":
        collected = state.get("collected_arguments", {})
        minimum = (
            collected.get("date_from")
            if field in {"date_to", "end_date"}
            else trusted_today(str(state["trusted_context"]["timezone"]))
            if field in {"date_from", "start_date"}
            and tool_name == "leave_create_request"
            else None
        )
        clarification.update(
            {
                "min_date": str(minimum) if minimum else None,
                "max_date": None,
                "initial_date": None,
            }
        )
    workflow_data["clarification_metadata"] = clarification
    await runtime.context.conversation_service.update(
        conversation,
        status=ConversationStatus.AWAITING_CLARIFICATION,
        pending_tool_name=tool_name,
        collected_arguments=state.get("collected_arguments", {}),
        missing_arguments=missing,
        ambiguous_arguments=ambiguous,
        workflow_data=workflow_data,
        entity_memory=state.get("entity_memory", {}),
    )
    data: dict[str, object] = {
        "message_type": "clarification",
        "text": question,
        "clarification": clarification,
    }
    update = stage_update(
        state,
        event="clarification_required",
        timing_name="pending_action_ms",
        started=started,
        data={"field": field},
    )
    update.update(
        {
            "response_type": ChatResponseType.CLARIFICATION_REQUIRED,
            "response_text": question,
            "response_data": data,
            "workflow_data": workflow_data,
        }
    )
    return update
