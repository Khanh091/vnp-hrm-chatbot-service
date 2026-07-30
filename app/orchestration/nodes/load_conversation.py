from time import perf_counter

from langgraph.runtime import Runtime

from app.orchestration.context import GraphContext
from app.orchestration.nodes.common import stage_update
from app.orchestration.state import ChatGraphState
from app.tools.definitions import TrustedExecutionContext


async def load_conversation_node(
    state: ChatGraphState, runtime: Runtime[GraphContext]
) -> dict[str, object]:
    started = perf_counter()
    trusted = TrustedExecutionContext.model_validate(state["trusted_context"])
    item = await runtime.context.conversation_service.load_or_create(
        state["conversation_id"], trusted
    )
    update = stage_update(
        state,
        event="conversation_loaded",
        timing_name="conversation_load_ms",
        started=started,
    )
    update.update(
        {
            "conversation_status": item.status,
            "conversation_version": item.version,
            "pending_tool_name": item.pending_tool_name,
            "collected_arguments": item.collected_arguments,
            "missing_arguments": item.missing_arguments,
            "ambiguous_arguments": item.ambiguous_arguments,
            "workflow_data": item.workflow_data,
            "entity_memory": item.entity_memory,
        }
    )
    return update
