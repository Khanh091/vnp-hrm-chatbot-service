from time import perf_counter

from langgraph.runtime import Runtime

from app.context.conversation import ConversationStatus
from app.orchestration.context import GraphContext
from app.orchestration.nodes.common import stage_update
from app.orchestration.state import ChatGraphState
from app.tools.definitions import TrustedExecutionContext, ValidatedToolExecution


async def execute_read_tool_node(
    state: ChatGraphState, runtime: Runtime[GraphContext]
) -> dict[str, object]:
    started = perf_counter()
    tool_name = state["pending_tool_name"]
    assert tool_name is not None
    result = await runtime.context.tool_executor.execute_validated(
        ValidatedToolExecution(
            tool_name=tool_name,
            arguments=state.get("collected_arguments", {}),
            trusted_context=TrustedExecutionContext.model_validate(
                state["trusted_context"]
            ),
        )
    )
    conversation = await runtime.context.conversation_service.load_owned(
        state["conversation_id"],
        int(state["trusted_context"]["odoo_user_id"]),
    )
    await runtime.context.conversation_service.update(
        conversation,
        status=(
            ConversationStatus.COMPLETED
            if result.success
            else ConversationStatus.FAILED
        ),
    )
    update = stage_update(
        state,
        event="tool_execution_completed",
        timing_name="odoo_execution_ms",
        started=started,
        data={
            "tool_name": tool_name,
            "success": result.success,
            "error_code": result.error_code,
        },
    )
    update["tool_result"] = result.model_dump(mode="json")
    return update
