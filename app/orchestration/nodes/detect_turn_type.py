from time import perf_counter

from langgraph.runtime import Runtime

from app.context.conversation import ConversationStatus
from app.orchestration.context import GraphContext
from app.orchestration.nodes.common import stage_update
from app.orchestration.state import ChatGraphState, ChatResponseType, TurnType


async def detect_turn_type_node(
    state: ChatGraphState, runtime: Runtime[GraphContext]
) -> dict[str, object]:
    started = perf_counter()
    action_type = state.get("action_type")
    awaiting_clarification = (
        state.get("conversation_status")
        == ConversationStatus.AWAITING_CLARIFICATION.value
    )
    if action_type == "confirm":
        turn_type = TurnType.CONFIRMATION_ACCEPT
    elif action_type == "cancel":
        turn_type = TurnType.CONFIRMATION_CANCEL
    elif action_type == "cancel_workflow":
        turn_type = TurnType.WORKFLOW_CANCEL
    elif awaiting_clarification:
        turn_type = runtime.context.dialog_turn_manager.detect(
            message=state.get("user_message"),
            structured_clarification=state.get("clarification"),
            expected_field=state.get("workflow_data", {}).get(
                "current_field"
            ),
        )
    else:
        turn_type = TurnType.NEW_QUERY
    if (
        awaiting_clarification
        and turn_type
        in {TurnType.NEW_QUERY_OVERRIDE, TurnType.WORKFLOW_CANCEL}
    ):
        await runtime.context.conversation_service.clear_active_workflow(
            state["conversation_id"],
            int(state["trusted_context"]["odoo_user_id"]),
        )
    update = stage_update(
        state,
        event="turn_detected",
        timing_name="turn_detection_ms",
        started=started,
        data={"turn_type": turn_type.value},
    )
    update["turn_type"] = turn_type
    if (
        turn_type
        in {TurnType.NEW_QUERY_OVERRIDE, TurnType.WORKFLOW_CANCEL}
        and awaiting_clarification
    ):
        update.update(
            {
                "conversation_status": ConversationStatus.ACTIVE.value,
                "pending_tool_name": None,
                "collected_arguments": {},
                "missing_arguments": [],
                "ambiguous_arguments": [],
                "workflow_data": {},
            }
        )
    if turn_type is TurnType.WORKFLOW_CANCEL:
        update.update(
            {
                "conversation_status": ConversationStatus.ACTIVE.value,
                "response_type": ChatResponseType.ANSWER,
                "response_text": "Đã hủy quy trình đang thực hiện.",
                "response_data": {"status": "cancelled"},
            }
        )
    return update
