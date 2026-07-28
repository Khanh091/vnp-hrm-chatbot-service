from time import perf_counter

from langgraph.runtime import Runtime

from app.orchestration.context import GraphContext
from app.orchestration.nodes.common import stage_update
from app.orchestration.state import ChatGraphState
from app.persistence.models.pending_action import PendingAction


def _action_data(item: PendingAction) -> dict[str, object]:
    return {
        "action_id": item.action_id,
        "conversation_id": item.conversation_id,
        "tool_name": item.tool_name,
        "tool_version": item.tool_version,
        "status": item.status,
    }


async def load_pending_action_confirm_node(
    state: ChatGraphState, runtime: Runtime[GraphContext]
) -> dict[str, object]:
    started = perf_counter()
    item = await runtime.context.pending_action_service.claim_execution(
        state.get("action_id") or "",
        conversation_id=state["conversation_id"],
        odoo_user_id=int(state["trusted_context"]["odoo_user_id"]),
    )
    update = stage_update(
        state,
        event="tool_execution_started",
        timing_name="pending_action_ms",
        started=started,
        data={"action_id": item.action_id, "tool_name": item.tool_name},
    )
    update["pending_action"] = _action_data(item)
    update["pending_tool_name"] = item.tool_name
    return update


async def load_pending_action_cancel_node(
    state: ChatGraphState, runtime: Runtime[GraphContext]
) -> dict[str, object]:
    started = perf_counter()
    item = await runtime.context.pending_action_service.load_owned(
        state.get("action_id") or "",
        conversation_id=state["conversation_id"],
        odoo_user_id=int(state["trusted_context"]["odoo_user_id"]),
    )
    update = stage_update(
        state,
        event="pending_action_loaded",
        timing_name="pending_action_ms",
        started=started,
        data={"action_id": item.action_id},
    )
    update["pending_action"] = _action_data(item)
    update["pending_tool_name"] = item.tool_name
    return update
