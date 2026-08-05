import re
from datetime import date
from time import perf_counter
from typing import Any

from langgraph.runtime import Runtime

from app.common.capability_outcomes import (
    CapabilityOutcome,
    public_outcome_message,
)
from app.context.date_resolver import AmbiguousDateExpression
from app.context.entities import SubjectMention
from app.context.entity_memory import ConversationEntityMemory
from app.context.entity_resolver import EntityOption
from app.context.subject_resolver import SubjectResolutionStatus
from app.orchestration.context import GraphContext
from app.orchestration.nodes.common import stage_update, trusted_today
from app.orchestration.state import ChatGraphState, ChatResponseType, WorkflowStatus
from app.routing.schemas import ToolSelection
from app.routing.taxonomy import SubjectType
from app.tools.definitions import TrustedExecutionContext, ValidatedToolExecution
from app.workflows.leave_action import (
    LeaveRequestSnapshot,
    trusted_selected_request,
    validated_patch,
)
from app.workflows.slot_manager import SlotState
from app.workflows.structured_answer import (
    DATE_SLOT_NAMES,
    InvalidStructuredSelection,
    validate_structured_selection,
)


def merge_workflow_metadata(
    current: dict[str, Any],
    *,
    options: list[dict[str, Any]],
    slot_issues: list[dict[str, Any]],
) -> dict[str, Any]:
    updated = {**current, "slot_issues": slot_issues}
    if options:
        updated["clarification_options"] = options
    return updated


async def merge_clarification_node(
    state: ChatGraphState, runtime: Runtime[GraphContext]
) -> dict[str, object]:
    started = perf_counter()
    tool_name = state.get("pending_tool_name")
    if not tool_name:
        outcome = CapabilityOutcome.INVALID
        await runtime.context.conversation_service.clear_workflow(
            state["conversation_id"],
            int(state["trusted_context"]["odoo_user_id"]),
        )
        return {
            **stage_update(
                state,
                event="clarification_context_missing",
                timing_name="argument_merge_ms",
                started=started,
            ),
            "workflow_issues": [{"code": "CLARIFICATION_CONTEXT_MISSING"}],
            "pending_tool_name": None,
            "workflow_status": WorkflowStatus.FAILED,
            "response_type": ChatResponseType.ERROR,
            "capability_outcome": outcome,
            "response_text": public_outcome_message(outcome),
            "response_data": None,
        }
    is_profile_workflow = tool_name == "profile_crud_workflow"
    tool = (
        None
        if is_profile_workflow
        else runtime.context.tool_registry.get(tool_name)
    )
    if tool is not None and not tool.enabled:
        outcome = CapabilityOutcome.UNSUPPORTED
        await runtime.context.conversation_service.clear_workflow(
            state["conversation_id"],
            int(state["trusted_context"]["odoo_user_id"]),
        )
        return {
            **stage_update(
                state,
                event="pending_tool_disabled",
                timing_name="argument_merge_ms",
                started=started,
            ),
            "workflow_issues": [{"code": "PENDING_TOOL_DISABLED"}],
            "pending_tool_name": None,
            "workflow_status": WorkflowStatus.FAILED,
            "response_type": ChatResponseType.UNSUPPORTED,
            "capability_outcome": outcome,
            "response_text": public_outcome_message(outcome),
            "response_data": None,
        }
    workflow = runtime.context.workflow_registry.get(tool_name)
    missing = list(state.get("missing_arguments", []))
    ambiguous = list(state.get("ambiguous_arguments", []))
    field: str | None
    current_field = state.get("workflow_data", {}).get("current_field")
    if isinstance(current_field, str):
        field = current_field
    elif workflow:
        field = workflow.next_field(missing, ambiguous)
    else:
        unresolved = ambiguous or missing
        field = unresolved[0] if unresolved else None
    message = (state.get("user_message") or "").strip()
    arguments = dict(state.get("collected_arguments", {}))
    options: list[dict[str, object]] = []
    subject_resolution_data: dict[str, object] | None = None
    resolved = False
    workflow_overrides: dict[str, Any] = {}
    trusted_data = state["trusted_context"]
    structured = state.get("clarification")
    validated_user_message: str | None = None
    validated_structured: dict[str, Any] | None = None
    if isinstance(structured, dict):
        allowed_options = [
            item
            for item in state.get("workflow_data", {}).get(
                "clarification_options", []
            )
            if isinstance(item, dict)
        ]
        metadata = state.get("workflow_data", {}).get(
            "clarification_metadata", {}
        )
        answer_type = structured.get("answer_type")
        if (
            is_profile_workflow
            and answer_type in {"profile_field_edit", "profile_edit_action"}
        ):
            expected_session = state.get("workflow_data", {}).get(
                "profile_edit_session_id"
            )
            if (
                not expected_session
                or structured.get("session_id") != expected_session
                or not isinstance(metadata, dict)
            ):
                return _invalid_structured_selection(state, started, field)
            if answer_type == "profile_edit_action":
                allowed_actions = {
                    str(item.get("value"))
                    for item in allowed_options
                    if isinstance(item, dict)
                }
                action = str(structured.get("value") or "")
                if action not in allowed_actions:
                    return _invalid_structured_selection(state, started, field)
                arguments["profile_edit_action"] = action
                validated_user_message = str(structured.get("label") or action)
                validated_structured = dict(structured)
                resolved = True
            else:
                field_key = str(structured.get("field") or "")
                form_fields = {
                    str(item.get("field_key")): item
                    for item in metadata.get("fields", [])
                    if isinstance(item, dict) and item.get("field_key")
                }
                field_metadata = form_fields.get(field_key)
                if (
                    field_metadata is None
                    or field_metadata.get("readonly") is True
                    or field_key not in state.get("workflow_data", {}).get(
                        "profile_form_field_keys", []
                    )
                ):
                    return _invalid_structured_selection(state, started, field)
                value = structured.get("value")
                input_type = field_metadata.get("input_type")
                if input_type in {"single_select", "boolean"}:
                    allowed = {
                        str(item.get("value"))
                        for item in field_metadata.get("options", [])
                        if isinstance(item, dict)
                    }
                    if input_type == "boolean":
                        allowed.update({"true", "false"})
                    if str(value).lower() not in allowed:
                        return _invalid_structured_selection(state, started, field)
                elif input_type == "date":
                    try:
                        date.fromisoformat(str(value))
                    except ValueError:
                        return _invalid_structured_selection(state, started, field)
                elif input_type == "number":
                    try:
                        float(str(value))
                    except (TypeError, ValueError):
                        return _invalid_structured_selection(state, started, field)
                elif input_type == "attachment":
                    return _invalid_structured_selection(state, started, field)
                arguments[field_key] = value
                validated_user_message = str(
                    structured.get("label") or value or ""
                )
                validated_structured = dict(structured)
                resolved = True
            structured = None
        try:
            trusted_selection = validate_structured_selection(
                structured,
                expected_field=field,
                allowed_options=allowed_options,
                metadata=metadata if isinstance(metadata, dict) else {},
            )
        except (AttributeError, InvalidStructuredSelection, TypeError):
            if structured is not None:
                return _invalid_structured_selection(state, started, field)
        else:
            structured_value = trusted_selection.value
            validated_user_message = trusted_selection.display_label
            validated_structured = {
                "field": field,
                "value": trusted_selection.value,
                "label": validated_user_message,
                "answer_type": trusted_selection.answer_type,
                "slot_name": structured.get("slot_name") or field,
            }
            message = validated_user_message
            structured = validated_structured
    if (
        field
        and isinstance(structured, dict)
        and structured.get("field") == field
        and isinstance(structured.get("value"), (bool, float, int, str))
    ):
        structured_value = structured["value"]
        if field in DATE_SLOT_NAMES and structured.get("answer_type") == "date_select":
            arguments[field] = trusted_selection.business_value
            resolved = True
        elif (
            field in {"changes", "changes_multi"}
            and tool_name == "leave_update_request"
        ):
            known = {
                str(item.get("value"))
                for item in state.get("workflow_data", {}).get(
                    "clarification_options", []
                )
                if isinstance(item, dict)
            }
            selected_structured_field = str(structured_value)
            if (
                field == "changes" and selected_structured_field in known
                and selected_structured_field != "multiple"
            ):
                workflow_overrides.update(
                    {
                        "selected_change_fields": [selected_structured_field],
                        "multi_edit_mode": False,
                        "current_field": selected_structured_field,
                        "clarification_options": [],
                    }
                )
            elif (
                field == "changes"
                and selected_structured_field == "multiple"
                and selected_structured_field in known
            ):
                workflow_overrides.update(
                    {
                        "selected_change_fields": [],
                        "multi_edit_mode": True,
                        "current_field": "changes_multi",
                        "clarification_options": [],
                    }
                )
            elif (
                field == "changes_multi"
                and selected_structured_field == "done"
                and selected_structured_field in known
                and state.get("workflow_data", {}).get("validated_patch")
            ):
                patch = dict(state["workflow_data"]["validated_patch"])
                arguments = {
                    "request_id": state.get("collected_arguments", {}).get(
                        "request_id"
                    ),
                    "changes": patch,
                }
                workflow_overrides.update(
                    {
                        "multi_edit_mode": False,
                        "current_field": None,
                        "clarification_options": [],
                    }
                )
                resolved = True
            elif (
                field == "changes_multi"
                and selected_structured_field in known
            ):
                workflow_overrides.update(
                    {
                        "selected_change_fields": [selected_structured_field],
                        "current_field": selected_structured_field,
                        "clarification_options": [],
                    }
                )
        elif field == "request_id":
            known_options = [
                item
                for item in state.get("workflow_data", {}).get(
                    "clarification_options", []
                )
                if isinstance(item, dict)
            ]
            selected_request = trusted_selected_request(known_options, structured_value)
            if selected_request is not None:
                arguments[field] = selected_request
                options = known_options
                # Keep the already allowlisted request across the next graph node.
                # The generic resolved-slot cleanup removes clarification_options,
                # so resolve_arguments must be able to trust this validated ref.
                workflow_overrides["selected_request_ref"] = selected_request
                resolved = True
        elif field == "leave_type_id":
            leave_type_options = [
                EntityOption.model_validate(item)
                for item in state.get("workflow_data", {}).get(
                    "clarification_options",
                    [],
                )
            ]
            if isinstance(structured_value, (int, str)) and any(
                str(option.value) == str(structured_value)
                for option in leave_type_options
            ):
                arguments[field] = int(str(structured_value))
                options = [item.model_dump(mode="json") for item in leave_type_options]
                resolved = True
        elif field in {"employee_id", "department_id"}:
            subject_options = [
                item
                for item in state.get("workflow_data", {}).get(
                    "clarification_options",
                    [],
                )
                if isinstance(item, dict)
            ]
            if isinstance(structured_value, (int, str)) and any(
                str(item.get("value")) == str(structured_value)
                for item in subject_options
            ):
                arguments[field] = int(str(structured_value))
                options = subject_options
                resolved = True
        else:
            arguments[field] = structured_value
            resolved = True
    elif field in {"date", "date_from", "date_to"}:
        try:
            value = runtime.context.date_resolver.resolve(
                message,
                current_date=trusted_today(str(trusted_data["timezone"])),
                timezone=str(trusted_data["timezone"]),
            )
        except AmbiguousDateExpression:
            value = None
            if field:
                ambiguous.append(field)
        if value is not None:
            if field == "date" and value.date_from == value.date_to:
                arguments[field] = value.date_from
                resolved = True
            elif field in {"date_from", "date_to"}:
                arguments[field] = (
                    value.date_from if field == "date_from" else value.date_to
                )
                resolved = True
    elif field == "changes" and tool_name == "leave_update_request":
        folded = " ".join(message.casefold().split())
        selected_field = (
            "date_from"
            if "ngày bắt đầu" in folded
            else "date_to"
            if "ngày kết thúc" in folded
            else "leave_type_id"
            if "loại nghỉ" in folded
            else "reason"
            if "lý do" in folded
            else None
        )
        if selected_field is not None:
            direct_value: Any | None = None
            if selected_field in {"date_from", "date_to"}:
                try:
                    parsed = runtime.context.date_resolver.resolve(
                        message,
                        current_date=trusted_today(str(trusted_data["timezone"])),
                        timezone=str(trusted_data["timezone"]),
                    )
                except AmbiguousDateExpression:
                    parsed = None
                if parsed is not None:
                    direct_value = (
                        parsed.date_from
                        if selected_field == "date_from"
                        else parsed.date_to
                    )
            elif selected_field == "reason":
                reason = re.search(r"(?:thành|sang)\s+(.+)$", message, re.IGNORECASE)
                if reason:
                    direct_value = reason.group(1).strip()
            elif selected_field == "leave_type_id":
                lookup = await runtime.context.tool_executor.execute_validated(
                    ValidatedToolExecution(
                        tool_name="leave_get_types",
                        arguments={},
                        trusted_context=TrustedExecutionContext.model_validate(
                            trusted_data
                        ),
                    )
                )
                if lookup.success:
                    typed_options = (
                        runtime.context.business_entity_resolver.leave_type_options(
                            lookup.data
                        )
                    )
                    target = re.search(
                        r"(?:thành|sang)\s+(.+)$", message, re.IGNORECASE
                    )
                    matched = (
                        runtime.context.business_entity_resolver.match_leave_type(
                            target.group(1).strip(), typed_options
                        )
                        if target
                        else None
                    )
                    if matched is not None:
                        direct_value = matched.value
                        options = [
                            item.model_dump(mode="json") for item in typed_options
                        ]
            snapshot_data = state.get("workflow_data", {}).get("original_snapshot")
            if direct_value is not None and isinstance(snapshot_data, dict):
                try:
                    patch = validated_patch(
                        LeaveRequestSnapshot.model_validate(snapshot_data),
                        {selected_field: direct_value},
                    )
                except (TypeError, ValueError):
                    pass
                else:
                    arguments = {
                        "request_id": state.get("collected_arguments", {}).get(
                            "request_id"
                        ),
                        "changes": patch,
                    }
                    resolved = True
                    workflow_overrides.update(
                        {
                            "validated_patch": patch,
                            "changed_fields": list(patch),
                            "clarification_options": [],
                            **(
                                {"leave_type_options": options}
                                if selected_field == "leave_type_id"
                                else {}
                            ),
                        }
                    )
            workflow_overrides.update(
                {
                    "selected_change_fields": [selected_field],
                    **({} if resolved else {"current_field": selected_field}),
                    "clarification_options": [],
                }
            )
    elif field == "request_id":
        mention = runtime.context.entity_resolver.extract_subject(message)
        reference = runtime.context.entity_memory_service.resolve_leave_request(
            mention,
            ConversationEntityMemory.model_validate(state.get("entity_memory", {})),
        )
        allowed_values = {
            str(item.get("value"))
            for item in state.get("workflow_data", {}).get("clarification_options", [])
            if isinstance(item, dict)
        }
        if reference is not None and str(reference.entity_id) in allowed_values:
            arguments[field] = int(str(reference.entity_id))
            resolved = True
    elif field == "leave_type_id":
        typed_options = [
            EntityOption.model_validate(item)
            for item in state.get("workflow_data", {}).get(
                "clarification_options",
                [],
            )
        ]
        if not typed_options:
            lookup = await runtime.context.tool_executor.execute_validated(
                ValidatedToolExecution(
                    tool_name="leave_get_types",
                    arguments={},
                    trusted_context=TrustedExecutionContext.model_validate(
                        trusted_data
                    ),
                )
            )
            if lookup.success:
                typed_options = (
                    runtime.context.business_entity_resolver.leave_type_options(
                        lookup.data
                    )
                )
        options = [item.model_dump(mode="json") for item in typed_options]
        numeric = re.fullmatch(r"\s*(\d+)\s*", message)
        matched = (
            next(
                (
                    option
                    for option in typed_options
                    if numeric and option.value == int(numeric.group(1))
                ),
                None,
            )
            if numeric
            else (
                runtime.context.business_entity_resolver.match_leave_type(
                    message,
                    typed_options,
                )
            )
        )
        if matched is not None:
            arguments[field] = matched.value
            resolved = True
    elif field in {"employee_id", "department_id"} and message:
        subject_resolution = await runtime.context.subject_resolver.resolve(
            SubjectMention(
                type=(
                    SubjectType.EMPLOYEE
                    if field == "employee_id"
                    else SubjectType.DEPARTMENT
                ),
                employee_name=message if field == "employee_id" else None,
                department_name=message if field == "department_id" else None,
            ),
            TrustedExecutionContext.model_validate(trusted_data).actor_context,
        )
        subject_resolution_data = subject_resolution.model_dump(mode="json")
        options = [
            option.model_dump(mode="json") for option in subject_resolution.options
        ]
        if (
            subject_resolution.status is SubjectResolutionStatus.RESOLVED
            and subject_resolution.subject is not None
        ):
            subject_value = (
                subject_resolution.subject.employee_id
                if field == "employee_id"
                else subject_resolution.subject.department_id
            )
            if subject_value is not None:
                arguments[field] = subject_value
                resolved = True
    elif field:
        arguments[field] = message
        resolved = bool(message)

    if (
        tool_name == "leave_update_request"
        and field in {"date_from", "date_to", "leave_type_id", "reason"}
        and resolved
    ):
        snapshot_data = state.get("workflow_data", {}).get("original_snapshot")
        if isinstance(snapshot_data, dict):
            raw_changes = dict(
                state.get("workflow_data", {}).get("validated_patch", {})
            )
            raw_changes[field] = arguments[field]
            try:
                patch = validated_patch(
                    LeaveRequestSnapshot.model_validate(snapshot_data),
                    raw_changes,
                )
            except (TypeError, ValueError):
                resolved = False
                if field == "date_from":
                    workflow_overrides["clarification_error"] = (
                        "Ngày bắt đầu không được sau ngày kết thúc."
                    )
                elif field == "date_to":
                    workflow_overrides["clarification_error"] = (
                        "Ngày kết thúc không được trước ngày bắt đầu."
                    )
            else:
                arguments = {
                    "request_id": state.get("collected_arguments", {}).get(
                        "request_id"
                    ),
                    "changes": patch,
                }
                workflow_overrides.update(
                    {
                        "validated_patch": patch,
                        "changed_fields": list(patch),
                        "clarification_options": [],
                        **(
                            {"leave_type_options": options}
                            if field == "leave_type_id"
                            else {}
                        ),
                    }
                )
                if state.get("workflow_data", {}).get("multi_edit_mode"):
                    arguments = {
                        "request_id": state.get("collected_arguments", {}).get(
                            "request_id"
                        )
                    }
                    workflow_overrides.update(
                        {
                            "multi_edit_mode": True,
                            "current_field": "changes_multi",
                        }
                    )
                    resolved = False

    if resolved and field:
        missing = [item for item in missing if item != field]
        ambiguous = [item for item in ambiguous if item != field]
    slot_issues: list[dict[str, Any]] = []
    if workflow:
        slot_state = runtime.context.slot_manager.merge(
            workflow,
            SlotState(
                values=state.get("collected_arguments", {}),
                missing=missing,
                ambiguous=ambiguous,
            ),
            arguments,
        )
        arguments = slot_state.values
        missing = runtime.context.slot_manager.get_missing_slots(
            workflow,
            slot_state,
        )
        ambiguous = slot_state.ambiguous
        slot_issues = [issue.model_dump(mode="json") for issue in slot_state.issues]
    persisted_selection = state.get("workflow_data", {}).get("selection")
    selection = (
        ToolSelection.model_validate(persisted_selection)
        if persisted_selection
        else ToolSelection(
            selected_tool=tool_name,
            confidence=1,
            extracted_arguments={},
            reason_code="CLARIFICATION_RESUME",
        )
    )
    selection = selection.model_copy(
        update={
            "extracted_arguments": {},
            "missing_arguments": [],
            "ambiguous_arguments": [],
            "requires_clarification": False,
            "clarification_question": None,
        }
    )
    update = stage_update(
        state,
        event="clarification_merged",
        timing_name="argument_merge_ms",
        started=started,
        data={"field": field, "resolved": resolved},
    )
    updated_workflow_data = merge_workflow_metadata(
        state.get("workflow_data", {}),
        options=options,
        slot_issues=slot_issues,
    )
    updated_workflow_data.update(workflow_overrides)
    if resolved:
        updated_workflow_data.pop("current_field", None)
        updated_workflow_data["clarification_options"] = []
        updated_workflow_data.pop("clarification_metadata", None)
    if subject_resolution_data is not None:
        updated_workflow_data["subject_resolution"] = subject_resolution_data
    update.update(
        {
            "classification": updated_workflow_data.get(
                "classification", state.get("classification", {})
            ),
            "candidate_contexts": updated_workflow_data.get(
                "candidate_contexts", state.get("candidate_contexts", [])
            ),
            "selection": selection.model_dump(mode="json"),
            "collected_arguments": arguments,
            "missing_arguments": missing,
            "ambiguous_arguments": ambiguous,
            "workflow_data": updated_workflow_data,
            "user_message": validated_user_message or state.get("user_message"),
            "clarification": validated_structured or state.get("clarification"),
        }
    )
    return update


def _invalid_structured_selection(
    state: ChatGraphState,
    started: float,
    expected_field: str | None,
) -> dict[str, object]:
    return {
        **stage_update(
            state,
            event="invalid_structured_selection",
            timing_name="argument_merge_ms",
            started=started,
            data={"expected_field": expected_field},
        ),
        "response_type": ChatResponseType.ERROR,
        "capability_outcome": CapabilityOutcome.INVALID,
        "response_text": (
            "Lựa chọn này không còn hợp lệ. "
            "Vui lòng chọn lại từ danh sách hiện tại."
        ),
        "response_data": {"error_code": "INVALID_STRUCTURED_SELECTION"},
        "user_message": None,
        "clarification": None,
    }
