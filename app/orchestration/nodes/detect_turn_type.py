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
    workflow_data = dict(state.get("workflow_data", {}))
    profile_changes = dict(
        workflow_data.get("profile_changes")
        or state.get("profile_changes", {})
    )
    guards_profile_draft = (
        starting_new_query
        and awaiting_clarification
        and state.get("pending_tool_name") == "profile_crud_workflow"
        and bool(profile_changes)
        and state.get("clarification") is None
    )
    if guards_profile_draft:
        deferred_query = str(state.get("user_message") or "").strip()
        previous_metadata = workflow_data.get("clarification_metadata", {})
        session_id = workflow_data.get("profile_edit_session_id")
        options = [
            {"value": "continue", "label": "Tiếp tục chỉnh sửa"},
            {"value": "switch_save_draft", "label": "Lưu nháp"},
            {
                "value": "switch_discard",
                "label": "Bỏ thay đổi và chuyển câu hỏi mới",
            },
        ]
        metadata = {
            **(previous_metadata if isinstance(previous_metadata, dict) else {}),
            "input_type": "edit_session_actions",
            "slot_name": "profile_edit_action",
            "session_id": session_id,
            "status": "OVERRIDE_GUARD",
            "options": options,
        }
        workflow_data.update({
            "profile_changes": profile_changes,
            "profile_deferred_query": deferred_query,
            "profile_edit_status": "OVERRIDE_GUARD",
            "current_field": "profile_edit_action",
            "clarification_options": options,
            "clarification_metadata": metadata,
        })
        conversation = await runtime.context.conversation_service.load_owned(
            state["conversation_id"],
            int(state["trusted_context"]["odoo_user_id"]),
        )
        await runtime.context.conversation_service.update(
            conversation,
            status=ConversationStatus.AWAITING_CLARIFICATION,
            pending_tool_name="profile_crud_workflow",
            workflow_data=workflow_data,
        )
        text = (
            "Bạn đang có thay đổi chưa lưu. Hãy chọn cách xử lý trước khi "
            "chuyển sang câu hỏi mới."
        )
        update = stage_update(
            state,
            event="profile_new_query_guarded",
            timing_name="turn_detection_ms",
            started=started,
            data={"deferred_query": True},
        )
        update.update({
            "turn_type": TurnType.PROFILE_OVERRIDE_GUARD,
            "conversation_status": ConversationStatus.AWAITING_CLARIFICATION.value,
            "workflow_data": workflow_data,
            "response_type": ChatResponseType.CLARIFICATION_REQUIRED,
            "response_text": text,
            "response_data": {
                "message_type": "clarification",
                "text": text,
                "clarification": metadata,
            },
        })
        return update
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
