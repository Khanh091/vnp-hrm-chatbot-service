from time import perf_counter

from langgraph.runtime import Runtime

from app.context.conversation import ConversationStatus
from app.orchestration.context import GraphContext
from app.orchestration.nodes.common import stage_update
from app.orchestration.state import ChatGraphState, ChatResponseType
from app.workflows.clarification_policy import clarification_question


async def ask_clarification_node(
    state: ChatGraphState, runtime: Runtime[GraphContext]
) -> dict[str, object]:
    started = perf_counter()
    tool_name = state["pending_tool_name"]
    assert tool_name is not None
    workflow = runtime.context.workflow_registry.get(tool_name)
    missing = state.get("missing_arguments", [])
    ambiguous = state.get("ambiguous_arguments", [])
    field = (
        workflow.next_field(missing, ambiguous)
        if workflow
        else (ambiguous or missing or ["details"])[0]
    )
    question = clarification_question(field or "details")
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
        "current_field": field,
    }
    await runtime.context.conversation_service.update(
        conversation,
        status=ConversationStatus.AWAITING_CLARIFICATION,
        pending_tool_name=tool_name,
        collected_arguments=state.get("collected_arguments", {}),
        missing_arguments=missing,
        ambiguous_arguments=ambiguous,
        workflow_data=workflow_data,
    )
    data: dict[str, object] = {
        "pending_tool": tool_name,
        "field": field,
        "missing_arguments": missing,
    }
    options = workflow_data.get("clarification_options")
    if options:
        data["options"] = options
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
