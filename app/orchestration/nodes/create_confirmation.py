import logging
from datetime import date, datetime
from time import perf_counter
from typing import Any

from langgraph.runtime import Runtime

from app.context.conversation import ConversationStatus
from app.orchestration.context import GraphContext
from app.orchestration.nodes.common import public_arguments, stage_update
from app.orchestration.state import ChatGraphState, ChatResponseType
from app.workflows.leave_action import (
    LeaveRequestSnapshot,
    confirmation_summary,
)

logger = logging.getLogger(__name__)


def _display_summary(arguments: dict[str, Any]) -> dict[str, Any]:
    summary = public_arguments(arguments)
    return {
        key: (
            value.strftime("%d/%m/%Y")
            if isinstance(value, date)
            else datetime.strptime(value, "%Y-%m-%d").strftime("%d/%m/%Y")
            if key in {"date", "date_from", "date_to"} and isinstance(value, str)
            else value
        )
        for key, value in summary.items()
        if value is not None and not (key == "request_unit" and value == "day")
    }


async def create_confirmation_node(
    state: ChatGraphState, runtime: Runtime[GraphContext]
) -> dict[str, object]:
    started = perf_counter()
    tool_name = state["pending_tool_name"]
    assert tool_name is not None
    tool = runtime.context.tool_registry.get(tool_name)
    trusted = state["trusted_context"]
    arguments = state.get("collected_arguments", {})
    summary = _display_summary(arguments)
    leave_type_id = summary.pop("leave_type_id", None)
    if leave_type_id is not None:
        options = state.get("workflow_data", {}).get("clarification_options", [])
        label = next(
            (
                item.get("label")
                for item in options
                if item.get("value") == leave_type_id
            ),
            None,
        )
        summary["leave_type"] = label or f"Loại nghỉ #{leave_type_id}"
    internal_summary = dict(summary)
    response_summary = summary
    leave_data = state.get("workflow_data", {})
    snapshot_data = leave_data.get("original_snapshot")
    if tool_name in {"leave_update_request", "leave_cancel_request"} and isinstance(
        snapshot_data, dict
    ):
        snapshot = LeaveRequestSnapshot.model_validate(snapshot_data)
        if tool_name == "leave_update_request":
            changes = arguments.get("changes", {})
            leave_type_label = next(
                (
                    item.get("label")
                    for item in leave_data.get("leave_type_options", [])
                    if str(item.get("value")) == str(changes.get("leave_type_id"))
                ),
                None,
            )
            response_summary = confirmation_summary(
                snapshot,
                changes,
                leave_type_label=leave_type_label,
            )
        else:
            response_summary = {
                "selected_request": (
                    f"{snapshot.date_from.strftime('%d/%m/%Y')}–"
                    f"{snapshot.date_to.strftime('%d/%m/%Y')} · "
                    f"{snapshot.leave_type} · "
                    f"{snapshot.state_label or snapshot.state}"
                )
            }
        internal_summary = {
            **response_summary,
            "request_id": snapshot.request_id,
            "original_snapshot": snapshot.model_dump(mode="json"),
            "original_version": snapshot.version,
            "validated_patch": arguments.get("changes", {}),
        }
        logger.info(
            "leave_confirmation tool_name=%s selected_request_ref=%s changed_fields=%s",
            tool_name,
            snapshot.request_id,
            list(arguments.get("changes", {})),
        )
    action = await runtime.context.pending_action_service.create(
        conversation_id=state["conversation_id"],
        odoo_user_id=int(trusted["odoo_user_id"]),
        tool_name=tool.name,
        tool_version=tool.version,
        validated_arguments=state.get("collected_arguments", {}),
        display_summary=internal_summary,
    )
    conversation = await runtime.context.conversation_service.load_owned(
        state["conversation_id"], int(trusted["odoo_user_id"])
    )
    await runtime.context.conversation_service.update(
        conversation,
        status=ConversationStatus.AWAITING_CONFIRMATION,
        pending_tool_name=tool.name,
        workflow_data={"pending_action_id": action.action_id},
    )
    workflow = runtime.context.workflow_registry.get(tool.name)
    title = workflow.confirmation_title if workflow else "Xác nhận thao tác"
    question = (
        workflow.confirmation_question
        if workflow
        else "Bạn có xác nhận thao tác này không?"
    )
    update = stage_update(
        state,
        event="confirmation_required",
        timing_name="pending_action_ms",
        started=started,
        data={"action_id": action.action_id, "tool_name": tool.name},
    )
    update.update(
        {
            "pending_action_id": action.action_id,
            "response_type": ChatResponseType.CONFIRMATION_REQUIRED,
            "response_text": question,
            "response_data": {
                "action_id": action.action_id,
                "title": title,
                "summary": response_summary,
                "expires_at": action.expires_at.isoformat(),
            },
        }
    )
    return update
