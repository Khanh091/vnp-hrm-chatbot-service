from time import perf_counter

from langgraph.runtime import Runtime

from app.context.conversation import ConversationStatus
from app.context.pending_action_service import PendingActionError
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
    awaiting_confirmation = (
        state.get("conversation_status")
        == ConversationStatus.AWAITING_CONFIRMATION.value
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
            expected_input_type=state.get("workflow_data", {}).get(
                "clarification_metadata", {}
            ).get("input_type"),
        )
    else:
        turn_type = TurnType.NEW_QUERY
    starting_new_query = turn_type in {
        TurnType.NEW_QUERY,
        TurnType.NEW_QUERY_OVERRIDE,
    }
    if starting_new_query and awaiting_confirmation:
        pending_action_id = state.get("workflow_data", {}).get(
            "pending_action_id"
        )
        if pending_action_id:
            try:
                await runtime.context.pending_action_service.cancel(
                    str(pending_action_id),
                    conversation_id=state["conversation_id"],
                    odoo_user_id=int(state["trusted_context"]["odoo_user_id"]),
                )
            except PendingActionError:
                # A terminal/expired action is already inactive and must not
                # prevent the explicit new request from being classified.
                pass
    if (
        (awaiting_clarification or awaiting_confirmation)
        and (
            turn_type in {TurnType.NEW_QUERY_OVERRIDE, TurnType.WORKFLOW_CANCEL}
            or starting_new_query
        )
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
    if starting_new_query or (
        turn_type is TurnType.WORKFLOW_CANCEL and awaiting_clarification
    ):
        update.update(
            {
                "conversation_status": ConversationStatus.ACTIVE.value,
                "pending_tool_name": None,
                "collected_arguments": {},
                "missing_arguments": [],
                "ambiguous_arguments": [],
                "workflow_data": {},
                "profile_section_key": None,
                "profile_resource_key": None,
                "profile_field_keys": [],
                "profile_record_reference": None,
                "profile_record_id": None,
                "profile_write_mode": None,
                "profile_current_snapshot": {},
                "profile_changes": {},
                "missing_profile_slots": [],
                "pending_action": {},
                "pending_action_id": None,
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
