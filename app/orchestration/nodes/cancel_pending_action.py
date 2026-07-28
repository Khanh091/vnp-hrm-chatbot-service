from time import perf_counter

from langgraph.runtime import Runtime

from app.context.conversation import ConversationStatus
from app.orchestration.context import GraphContext
from app.orchestration.nodes.common import stage_update
from app.orchestration.state import ChatGraphState, ChatResponseType


async def cancel_pending_action_node(
    state: ChatGraphState, runtime: Runtime[GraphContext]
) -> dict[str, object]:
    started = perf_counter()
    action_id = state.get("action_id") or ""
    item = await runtime.context.pending_action_service.cancel(
        action_id,
        conversation_id=state["conversation_id"],
        odoo_user_id=int(state["trusted_context"]["odoo_user_id"]),
    )
    conversation = await runtime.context.conversation_service.load_owned(
        state["conversation_id"],
        int(state["trusted_context"]["odoo_user_id"]),
    )
    await runtime.context.conversation_service.update(
        conversation, status=ConversationStatus.CANCELLED
    )
    update = stage_update(
        state,
        event="pending_action_cancelled",
        timing_name="pending_action_ms",
        started=started,
        data={"action_id": action_id},
    )
    update.update(
        {
            "response_type": ChatResponseType.ANSWER,
            "response_text": "Đã hủy thao tác.",
            "response_data": {
                "action_id": action_id,
                "status": item.status,
            },
        }
    )
    return update
