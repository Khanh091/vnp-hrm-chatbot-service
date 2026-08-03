import logging
import re
from time import perf_counter

from langgraph.runtime import Runtime

from app.common.capability_outcomes import CapabilityOutcome
from app.common.error_messages import public_error_message
from app.context.date_resolver import AmbiguousDateExpression
from app.context.entity_memory import ConversationEntityMemory
from app.orchestration.context import GraphContext
from app.orchestration.nodes.common import stage_update, trusted_today
from app.orchestration.state import ChatGraphState, ChatResponseType
from app.routing.schemas import ToolSelection
from app.routing.taxonomy import SubjectType
from app.tools.definitions import TrustedExecutionContext, ValidatedToolExecution
from app.workflows.leave_action import (
    LeaveRequestSnapshot,
    actionable_options,
    snapshot_from_payload,
    validated_patch,
)

logger = logging.getLogger(__name__)


async def resolve_arguments_node(
    state: ChatGraphState, runtime: Runtime[GraphContext]
) -> dict[str, object]:
    started = perf_counter()
    tool_name = state.get("pending_tool_name")
    if not tool_name:
        return stage_update(
            state,
            event="argument_resolution_skipped",
            timing_name="argument_resolution_ms",
            started=started,
        )
    tool = runtime.context.tool_registry.get(tool_name)
    selection = ToolSelection.model_validate(state["selection"])
    trusted = state["trusted_context"]
    trusted_context = TrustedExecutionContext.model_validate(trusted)
    workflow_data = dict(state.get("workflow_data", {}))
    entity_memory = ConversationEntityMemory.model_validate(
        state.get("entity_memory", {})
    )
    query_text = (
        ""
        if state.get("turn_type") == "clarification_answer"
        else state.get("normalized_query") or ""
    )
    trusted_request_id: int | None = None
    if tool_name in {"leave_update_request", "leave_cancel_request"}:
        action = "update" if tool_name == "leave_update_request" else "cancel"
        if not workflow_data.get("actionable_loaded"):
            actionable = await runtime.context.tool_executor.execute_validated(
                ValidatedToolExecution(
                    tool_name="leave_list_actionable_requests",
                    arguments={"action": action},
                    trusted_context=trusted_context,
                )
            )
            if not actionable.success:
                return {
                    **stage_update(
                        state,
                        event="leave_actionable_load_failed",
                        timing_name="argument_resolution_ms",
                        started=started,
                        data={
                            "tool_name": tool_name,
                            "error_code": actionable.error_code,
                        },
                    ),
                    "response_type": ChatResponseType.ERROR,
                    "capability_outcome": CapabilityOutcome.INVALID,
                    "response_text": public_error_message(actionable.error_code),
                    "response_data": {"error_code": actionable.error_code},
                }
            options = actionable_options(actionable.data)
            entity_memory = runtime.context.entity_memory_service.capture(
                tool_name="leave_list_actionable_requests",
                data=actionable.data,
                memory=entity_memory,
            )
            workflow_data.update(
                {
                    "actionable_loaded": True,
                    "action": action,
                    "actionable_count": len(options),
                    "clarification_options": options,
                    "current_field": "request_id",
                }
            )
            logger.info(
                "leave_workflow intent=leave.%s tool_name=%s actionable_count=%d",
                action,
                tool_name,
                len(options),
            )
            if not options:
                return {
                    **stage_update(
                        state,
                        event="leave_actionable_empty",
                        timing_name="argument_resolution_ms",
                        started=started,
                        data={"tool_name": tool_name, "actionable_count": 0},
                    ),
                    "response_type": ChatResponseType.ANSWER,
                    "capability_outcome": CapabilityOutcome.EMPTY,
                    "response_text": (
                        "Bạn hiện không có đơn nghỉ phép nào có thể sửa."
                        if action == "update"
                        else "Bạn hiện không có đơn nghỉ phép nào có thể hủy."
                    ),
                    "response_data": {"result": []},
                    "workflow_data": workflow_data,
                    "entity_memory": entity_memory.model_dump(mode="json"),
                    "pending_tool_name": None,
                }
            mention = runtime.context.entity_resolver.extract_subject(
                state.get("normalized_query") or state.get("user_message") or ""
            )
            reference = runtime.context.entity_memory_service.resolve_leave_request(
                mention, entity_memory
            )
            allowed = {item["value"] for item in options}
            if reference is not None and str(reference.entity_id) in allowed:
                trusted_request_id = int(str(reference.entity_id))
        else:
            allowed = {
                str(item.get("value"))
                for item in workflow_data.get("clarification_options", [])
                if isinstance(item, dict)
            }
            candidate = state.get("collected_arguments", {}).get("request_id")
            selected_ref = workflow_data.get("selected_request_ref")
            if candidate is not None and (
                str(candidate) in allowed or str(candidate) == str(selected_ref)
            ):
                trusted_request_id = int(candidate)

        if trusted_request_id is not None and not workflow_data.get(
            "original_snapshot"
        ):
            details = await runtime.context.tool_executor.execute_validated(
                ValidatedToolExecution(
                    tool_name="leave_get_request_details",
                    arguments={"request_id": trusted_request_id},
                    trusted_context=trusted_context,
                )
            )
            if not details.success:
                return {
                    **stage_update(
                        state,
                        event="leave_details_load_failed",
                        timing_name="argument_resolution_ms",
                        started=started,
                        data={"tool_name": tool_name, "error_code": details.error_code},
                    ),
                    "response_type": ChatResponseType.ERROR,
                    "capability_outcome": CapabilityOutcome.INVALID,
                    "response_text": public_error_message(details.error_code),
                    "response_data": {"error_code": details.error_code},
                }
            try:
                snapshot = snapshot_from_payload(details.data)
            except (KeyError, TypeError, ValueError):
                return {
                    **stage_update(
                        state,
                        event="leave_details_contract_failed",
                        timing_name="argument_resolution_ms",
                        started=started,
                    ),
                    "response_type": ChatResponseType.ERROR,
                    "capability_outcome": CapabilityOutcome.INVALID,
                    "response_text": public_error_message("LEAVE_REQUEST_NOT_FOUND"),
                    "response_data": {"error_code": "LEAVE_REQUEST_NOT_FOUND"},
                }
            permitted = (
                snapshot.can_update if action == "update" else snapshot.can_cancel
            )
            if not permitted:
                code = (
                    "LEAVE_REQUEST_NOT_EDITABLE"
                    if action == "update"
                    else "LEAVE_REQUEST_NOT_CANCELLABLE"
                )
                return {
                    **stage_update(
                        state,
                        event="leave_action_not_allowed",
                        timing_name="argument_resolution_ms",
                        started=started,
                        data={"tool_name": tool_name, "error_code": code},
                    ),
                    "response_type": ChatResponseType.ERROR,
                    "capability_outcome": CapabilityOutcome.INVALID,
                    "response_text": public_error_message(code),
                    "response_data": {"error_code": code},
                }
            workflow_data.update(
                {
                    "selected_request_ref": snapshot.request_id,
                    "original_snapshot": snapshot.model_dump(mode="json"),
                    "clarification_options": [],
                    "current_field": "changes" if action == "update" else None,
                }
            )
            logger.info(
                "leave_workflow intent=leave.%s tool_name=%s "
                "selected_request_ref=%s original_fields=%s",
                action,
                tool_name,
                snapshot.request_id,
                ["date_from", "date_to", "leave_type_id", "reason", "version"],
            )
        if (
            action == "update"
            and workflow_data.get("original_snapshot")
            and not workflow_data.get("validated_patch")
        ):
            original_text = str(
                workflow_data.get("original_query") or state.get("user_message") or ""
            )
            natural_changes: dict[str, object] = {}
            reason_match = re.search(
                r"(?:đổi|sửa|cập nhật)\s+lý do\s+(?:thành|sang)\s+(.+)$",
                original_text,
                re.IGNORECASE,
            )
            if reason_match:
                natural_changes["reason"] = reason_match.group(1).strip()
            date_field = (
                "date_from"
                if re.search(r"ngày\s+bắt\s+đầu", original_text, re.IGNORECASE)
                else "date_to"
                if re.search(r"ngày\s+kết\s+thúc", original_text, re.IGNORECASE)
                else None
            )
            if date_field:
                try:
                    resolved_date = runtime.context.date_resolver.resolve(
                        original_text,
                        current_date=trusted_today(str(trusted["timezone"])),
                        timezone=str(trusted["timezone"]),
                    )
                except AmbiguousDateExpression:
                    resolved_date = None
                if resolved_date is not None:
                    natural_changes[date_field] = (
                        resolved_date.date_from
                        if date_field == "date_from"
                        else resolved_date.date_to
                    )
            leave_type_match = re.search(
                r"(?:đổi|sửa|cập nhật)\s+loại\s+nghỉ\s+"
                r"(?:thành|sang)\s+(.+)$",
                original_text,
                re.IGNORECASE,
            )
            if leave_type_match:
                lookup = await runtime.context.tool_executor.execute_validated(
                    ValidatedToolExecution(
                        tool_name="leave_get_types",
                        arguments={},
                        trusted_context=trusted_context,
                    )
                )
                if lookup.success:
                    type_options = (
                        runtime.context.business_entity_resolver.leave_type_options(
                            lookup.data
                        )
                    )
                    matched_type = (
                        runtime.context.business_entity_resolver.match_leave_type(
                            leave_type_match.group(1).strip(), type_options
                        )
                    )
                    if matched_type is not None:
                        natural_changes["leave_type_id"] = matched_type.value
                        workflow_data["leave_type_options"] = [
                            item.model_dump(mode="json") for item in type_options
                        ]
            if natural_changes:
                try:
                    patch = validated_patch(
                        LeaveRequestSnapshot.model_validate(
                            workflow_data["original_snapshot"]
                        ),
                        natural_changes,
                    )
                except (TypeError, ValueError):
                    pass
                else:
                    workflow_data.update(
                        {
                            "validated_patch": patch,
                            "changed_fields": list(patch),
                            "current_field": None,
                        }
                    )
    resolution = runtime.context.argument_resolver.resolve(
        selection,
        tool,
        query=query_text,
        current_date=trusted_today(str(trusted["timezone"])),
        timezone=str(trusted["timezone"]),
        conversation_arguments=state.get("collected_arguments"),
    )
    subject_mention = runtime.context.entity_resolver.extract_subject(
        query_text or state.get("user_message") or ""
    )
    subject_resolution = None
    if subject_mention.type in {
        SubjectType.SELF,
        SubjectType.EMPLOYEE,
        SubjectType.DEPARTMENT,
    }:
        subject_resolution = await runtime.context.subject_resolver.resolve(
            subject_mention,
            trusted_context.actor_context,
        )
    resolved_arguments = dict(resolution.arguments)
    if tool_name in {"leave_update_request", "leave_cancel_request"}:
        if trusted_request_id is None:
            resolved_arguments.pop("request_id", None)
        else:
            resolved_arguments["request_id"] = trusted_request_id
        stored_patch = workflow_data.get("validated_patch")
        if (
            tool_name == "leave_update_request"
            and isinstance(stored_patch, dict)
            and not workflow_data.get("multi_edit_mode")
        ):
            resolved_arguments["changes"] = stored_patch
    resolved_subject = (
        subject_resolution.subject if subject_resolution is not None else None
    )
    if resolved_subject is not None:
        if (
            "employee_id" in tool.argument_schema.model_fields
            and resolved_subject.employee_id is not None
        ):
            resolved_arguments["employee_id"] = resolved_subject.employee_id
        if (
            "department_id" in tool.argument_schema.model_fields
            and resolved_subject.department_id is not None
        ):
            resolved_arguments["department_id"] = resolved_subject.department_id
    if (
        "request_id" in tool.argument_schema.model_fields
        and "request_id" not in resolved_arguments
    ):
        mention = runtime.context.entity_resolver.extract_subject(
            state.get("normalized_query") or state.get("user_message") or ""
        )
        reference = runtime.context.entity_memory_service.resolve_leave_request(
            mention,
            ConversationEntityMemory.model_validate(state.get("entity_memory", {})),
        )
        if reference is not None:
            try:
                resolved_arguments["request_id"] = int(reference.entity_id)
            except (TypeError, ValueError):
                pass
    workflow = runtime.context.workflow_registry.get(tool_name)
    slot_issues: list[dict[str, object]] = []
    if workflow is not None:
        slot_state = runtime.context.slot_manager.initialize(
            workflow,
            resolved_arguments,
        )
        arguments = slot_state.values
        missing = slot_state.missing
        ambiguous = list(
            dict.fromkeys([*resolution.ambiguous_arguments, *slot_state.ambiguous])
        )
        slot_issues = [issue.model_dump(mode="json") for issue in slot_state.issues]
    else:
        arguments = resolved_arguments
        missing = resolution.missing_arguments
        ambiguous = resolution.ambiguous_arguments
    update = stage_update(
        state,
        event="arguments_resolved",
        timing_name="argument_resolution_ms",
        started=started,
    )
    update.update(
        {
            "collected_arguments": arguments,
            "missing_arguments": missing,
            "ambiguous_arguments": ambiguous,
            "workflow_data": {
                **workflow_data,
                "transient_entities": resolution.transient_entities,
                "slot_issues": slot_issues,
                "rejected_trusted_fields": (resolution.rejected_trusted_fields),
                "subject_mention": subject_mention.model_dump(mode="json"),
                "subject_resolution": (
                    subject_resolution.model_dump(mode="json")
                    if subject_resolution is not None
                    else state.get("workflow_data", {}).get("subject_resolution")
                ),
                "clarification_options": (
                    [
                        option.model_dump(mode="json")
                        for option in subject_resolution.options
                    ]
                    if subject_resolution is not None and subject_resolution.options
                    else workflow_data.get(
                        "clarification_options",
                        [],
                    )
                ),
            },
            "entity_memory": entity_memory.model_dump(mode="json"),
        }
    )
    return update
