from __future__ import annotations

import unicodedata
from time import perf_counter
from typing import Any

from langgraph.runtime import Runtime

from app.common.capability_outcomes import CapabilityOutcome
from app.context.conversation import ConversationStatus
from app.integrations.odoo.profile_schema import (
    ProfileField,
    ProfileResource,
    ProfileSchemaError,
    ProfileWriteMode,
    input_type_for_field,
)
from app.orchestration.context import GraphContext
from app.orchestration.nodes.common import stage_update
from app.orchestration.state import ChatGraphState, ChatResponseType
from app.routing.profile_target_resolver import (
    ProfileTargetOutsideAllowlistError,
    ProfileTargetResolverError,
)
from app.routing.schemas import QueryClassification
from app.routing.taxonomy import Operation

PROFILE_WORKFLOW = "profile_crud_workflow"


async def resolve_profile_write_node(
    state: ChatGraphState,
    runtime: Runtime[GraphContext],
) -> dict[str, object]:
    started = perf_counter()
    trusted = state["trusted_context"]
    actor = int(trusted["odoo_user_id"])
    request_id = state["request_id"]
    classification = QueryClassification.model_validate(
        state.get("classification")
        or state.get("workflow_data", {}).get("classification")
    )
    operation = classification.operation
    if operation not in {Operation.CREATE, Operation.UPDATE, Operation.DELETE}:
        return _typed_error(
            state,
            started,
            "PROFILE_OPERATION_INVALID",
            "Thao tác hồ sơ chưa hợp lệ.",
            CapabilityOutcome.INVALID,
        )

    workflow_data = dict(state.get("workflow_data", {}))
    collected = dict(state.get("collected_arguments", {}))
    section_key = collected.get("profile_section_key") or workflow_data.get(
        "profile_section_key"
    )
    resource_key = collected.get("profile_resource_key") or workflow_data.get(
        "profile_resource_key"
    )
    field_keys = list(workflow_data.get("profile_field_keys", []))
    selected_field = collected.get("profile_field_keys")
    if selected_field:
        field_keys = [str(selected_field)]
    record_reference = workflow_data.get("profile_record_reference")
    record_id = workflow_data.get("profile_record_id")
    selected_record_id = collected.get("profile_record_id")
    structured_answer = state.get("clarification")

    if (
        isinstance(structured_answer, dict)
        and structured_answer.get("answer_type") == "option_select"
        and structured_answer.get("field")
        in {
            "profile_section_key",
            "profile_resource_key",
            "profile_field_keys",
            "profile_record_id",
        }
    ):
        workflow_data["profile_target_resolved"] = True
    if (
        selected_record_id is not None
        and isinstance(structured_answer, dict)
        and structured_answer.get("answer_type") == "option_select"
    ):
        try:
            record_id = int(selected_record_id)
        except (TypeError, ValueError):
            record_id = None
        else:
            workflow_data["profile_record_id"] = record_id
    elif isinstance(selected_record_id, str) and selected_record_id.strip():
        # A free-text follow-up is treated as a reference, never as an ORM id.
        record_reference = selected_record_id.strip()
        workflow_data["profile_record_reference"] = record_reference
    changes = dict(workflow_data.get("profile_changes", {}))
    for key in field_keys:
        if key in collected:
            changes[key] = collected[key]

    schema = runtime.context.profile_schema_client
    try:
        sections = await schema.get_sections(
            None,
            odoo_user_id=actor,
            request_id=request_id,
        )
        all_resources: list[ProfileResource] = []
        for section in sections:
            all_resources.extend(
                await schema.get_resources(
                    section.key,
                    None,
                    odoo_user_id=actor,
                    request_id=request_id,
                )
            )

        if not workflow_data.get("profile_target_resolved"):
            try:
                resolution = await runtime.context.profile_target_resolver.resolve(
                    original_query=state.get("user_message") or "",
                    intent=classification.intent,  # type: ignore[arg-type]
                    operation=operation,
                    sections=sections,
                    resources=tuple(all_resources),
                    request_id=request_id,
                )
                # Resolve fields only after the resource allowlist has narrowed.
                if resolution.resource_key:
                    detailed = await schema.get_resource(
                        resolution.resource_key,
                        odoo_user_id=actor,
                        request_id=request_id,
                    )
                    resolution = await runtime.context.profile_target_resolver.resolve(
                        original_query=state.get("user_message") or "",
                        intent=classification.intent,  # type: ignore[arg-type]
                        operation=operation,
                        sections=sections,
                        resources=(detailed,),
                        request_id=request_id,
                    )
                section_key = resolution.section_key
                resource_key = resolution.resource_key
                field_keys = resolution.field_keys
                record_reference = resolution.record_reference_text
                workflow_data["profile_resolution_reason"] = resolution.reason_code
            except ProfileTargetOutsideAllowlistError as error:
                workflow_data["profile_resolution_error"] = error.reason_code
                return await _clarify_section(
                    state,
                    runtime,
                    started,
                    sections,
                    classification,
                    operation,
                    workflow_data,
                    "Tôi chưa xác định được nhóm hồ sơ hợp lệ. Bạn muốn chọn phần nào?",
                )
            except ProfileTargetResolverError as error:
                workflow_data["profile_resolution_error"] = error.reason_code
                return await _clarify_section(
                    state,
                    runtime,
                    started,
                    sections,
                    classification,
                    operation,
                    workflow_data,
                    "Bạn muốn thay đổi phần hồ sơ nào?",
                )
            workflow_data["profile_target_resolved"] = True

        if not section_key:
            return await _clarify_section(
                state,
                runtime,
                started,
                sections,
                classification,
                operation,
                workflow_data,
                "Bạn muốn thay đổi phần hồ sơ nào?",
            )

        if not resource_key:
            resources = await schema.get_resources(
                str(section_key),
                operation,
                odoo_user_id=actor,
                request_id=request_id,
            )
            return await _clarification(
                state,
                runtime,
                started,
                classification,
                operation,
                workflow_data,
                section_key=str(section_key),
                resource_key=None,
                field_keys=[],
                record_reference=record_reference,
                changes=changes,
                slot_name="profile_resource_key",
                input_type="resource_select",
                text="Bạn muốn sửa nhóm thông tin nào?",
                options=_options(resources),
            )

        resource = await schema.get_resource(
            str(resource_key),
            odoo_user_id=actor,
            request_id=request_id,
        )
        if resource.section_key != section_key:
            raise ProfileTargetOutsideAllowlistError()
        if not resource.allows(operation):
            return _forbidden(state, started, "")

        selected_fields = [
            field for field in resource.fields if field.key in field_keys
        ]
        if len(selected_fields) != len(field_keys):
            raise ProfileTargetOutsideAllowlistError()
        forbidden_field = next(
            (field for field in selected_fields if not field.allows(operation)),
            None,
        )
        if forbidden_field is not None:
            return _forbidden(
                state,
                started,
                forbidden_field.description or "",
            )

        if (
            resource.resource_type == "collection"
            and operation in {Operation.UPDATE, Operation.DELETE}
            and record_id is None
        ):
            records = await schema.list_records(
                resource.key, odoo_user_id=actor, request_id=request_id
            )
            candidates = _match_records(records, record_reference)
            if not candidates:
                return _typed_error(
                    state, started, "PROFILE_RECORD_NOT_FOUND",
                    "Không tìm thấy dòng hồ sơ phù hợp.", CapabilityOutcome.EMPTY,
                )
            if len(candidates) == 1:
                record_id = candidates[0].record_id
                workflow_data["profile_record_id"] = record_id
            else:
                return await _clarification(
                    state, runtime, started, classification, operation, workflow_data,
                    section_key=str(section_key), resource_key=resource.key,
                    field_keys=field_keys, record_reference=record_reference,
                    changes=changes, slot_name="profile_record_id",
                    input_type="record_select",
                    text="Có nhiều dòng phù hợp. Bạn muốn chọn dòng nào?",
                    options=_record_options(candidates),
                )

        operation_fields = await schema.get_fields(
            resource.key,
            operation,
            odoo_user_id=actor,
            request_id=request_id,
        )
        if operation is Operation.CREATE:
            required = [item for item in operation_fields if item.required_on_create]
            missing = [item for item in required if item.key not in changes]
            if missing:
                return await _clarify_value(
                    state,
                    runtime,
                    started,
                    classification,
                    operation,
                    workflow_data,
                    resource,
                    missing[0],
                    field_keys,
                    record_reference,
                    changes,
                    missing_profile_slots=[item.key for item in missing],
                )
        elif operation is Operation.UPDATE:
            if not selected_fields:
                return await _clarification(
                    state,
                    runtime,
                    started,
                    classification,
                    operation,
                    workflow_data,
                    section_key=str(section_key),
                    resource_key=resource.key,
                    field_keys=[],
                    record_reference=record_reference,
                    changes=changes,
                    slot_name="profile_field_keys",
                    input_type="field_select",
                    text="Bạn muốn sửa thông tin nào?",
                    options=_options(operation_fields),
                )
            missing_values = [
                field for field in selected_fields if field.key not in changes
            ]
            if missing_values:
                return await _clarify_value(
                    state,
                    runtime,
                    started,
                    classification,
                    operation,
                    workflow_data,
                    resource,
                    missing_values[0],
                    field_keys,
                    record_reference,
                    changes,
                    missing_profile_slots=[item.key for item in missing_values],
                )

        relevant_fields = (
            selected_fields or list(operation_fields) or list(resource.fields)
        )
        write_mode = (
            ProfileWriteMode.APPROVAL_REQUEST
            if any(
                field.write_mode == ProfileWriteMode.APPROVAL_REQUEST
                for field in relevant_fields
            )
            else ProfileWriteMode.DIRECT
        )
        current_snapshot: dict[str, Any] = {}
        expected_version: str | None = None
        if operation is Operation.UPDATE:
            current = (
                await schema.get_current_snapshot(
                    resource.key, odoo_user_id=actor, request_id=request_id
                )
                if resource.resource_type == "singleton"
                else await schema.get_record(
                    resource.key, int(record_id), odoo_user_id=actor,
                    request_id=request_id,
                )
            )
            current_snapshot = dict(current.snapshot)
            expected_version = current.version
            changes = {
                key: value for key, value in changes.items()
                if not _same_value(current_snapshot.get(key), value)
            }
            if not changes:
                return _typed_error(
                    state, started, "PROFILE_INVALID_VALUE",
                    "Giá trị mới không khác thông tin hiện tại.",
                    CapabilityOutcome.INVALID,
                )
        elif operation is Operation.DELETE:
            current = await schema.get_record(
                resource.key, int(record_id), odoo_user_id=actor,
                request_id=request_id,
            )
            current_snapshot = dict(current.snapshot)
            expected_version = current.version

        profile_data = _profile_data(
            section_key=str(section_key), resource_key=resource.key,
            field_keys=field_keys, record_reference=record_reference,
            changes=changes, write_mode=write_mode, missing_profile_slots=[],
        )
        profile_data["profile_record_id"] = record_id
        profile_data["profile_current_snapshot"] = current_snapshot
        workflow_data.update(profile_data)
        return await _create_profile_confirmation(
            state, runtime, started, classification, resource, operation,
            selected_fields, record_id, current_snapshot, expected_version,
            changes, write_mode, workflow_data,
        )
    except ProfileTargetOutsideAllowlistError:
        return _typed_error(
            state,
            started,
            "PROFILE_TARGET_OUTSIDE_ALLOWLIST",
            "Lựa chọn hồ sơ không còn hợp lệ. Vui lòng chọn lại.",
            CapabilityOutcome.INVALID,
        )
    except ProfileSchemaError as error:
        error_texts = {
            "PROFILE_RESOURCE_NOT_FOUND": "Không tìm thấy nhóm hồ sơ.",
            "PROFILE_RECORD_NOT_FOUND": (
                "Không tìm thấy dòng hồ sơ thuộc tài khoản hiện tại."
            ),
            "PROFILE_OPERATION_FORBIDDEN": (
                "Bạn không được phép thực hiện thao tác này."
            ),
            "PROFILE_FIELD_NOT_WRITABLE": "Trường hồ sơ này không thể thay đổi.",
            "PROFILE_INVALID_VALUE": "Giá trị hồ sơ không hợp lệ.",
            "PROFILE_RECORD_CHANGED": "Dòng hồ sơ đã thay đổi; vui lòng kiểm tra lại.",
        }
        outcome = (
            CapabilityOutcome.NOT_FOUND
            if error.reason_code
            in {"PROFILE_RESOURCE_NOT_FOUND", "PROFILE_RECORD_NOT_FOUND"}
            else CapabilityOutcome.DENIED
            if error.reason_code
            in {"PROFILE_OPERATION_FORBIDDEN", "PROFILE_SCHEMA_ACCESS_DENIED"}
            else CapabilityOutcome.INVALID
        )
        return _typed_error(
            state,
            started,
            error.reason_code,
            error_texts.get(
                error.reason_code,
                "Không thể thực hiện thao tác hồ sơ.",
            ),
            outcome,
        )


async def _create_profile_confirmation(
    state: ChatGraphState,
    runtime: Runtime[GraphContext],
    started: float,
    classification: QueryClassification,
    resource: ProfileResource,
    operation: Operation,
    selected_fields: list[ProfileField],
    record_id: int | None,
    current_snapshot: dict[str, Any],
    expected_version: str | None,
    changes: dict[str, Any],
    write_mode: ProfileWriteMode,
    workflow_data: dict[str, Any],
) -> dict[str, object]:
    trusted = state["trusted_context"]
    arguments = {
        "intent": classification.intent.value,
        "operation": operation.value,
        "resource_key": resource.key,
        "record_id": record_id,
        "current_snapshot": current_snapshot,
        "expected_version": expected_version,
        "changes": changes,
        "write_mode": write_mode.value,
    }
    arguments = {key: value for key, value in arguments.items() if value is not None}
    summary = []
    for definition in selected_fields:
        if definition.key in changes:
            summary.append({
                "label": definition.label,
                "old_value": _display_value(current_snapshot.get(definition.key)),
                "new_value": _display_value(changes[definition.key]),
            })
    if operation is Operation.CREATE:
        fields_by_key = {field.key: field for field in resource.fields}
        summary = [
            {"label": fields_by_key[key].label, "old_value": None,
             "new_value": _display_value(value)}
            for key, value in changes.items() if key in fields_by_key
        ]
    elif operation is Operation.DELETE:
        summary = [{
            "label": resource.label,
            "old_value": _display_value(
                current_snapshot.get(resource.record_label_field or "")
            ) or f"#{record_id}",
            "new_value": None,
        }]
    action = await runtime.context.pending_action_service.create(
        conversation_id=state["conversation_id"],
        odoo_user_id=int(trusted["odoo_user_id"]),
        tool_name=PROFILE_WORKFLOW,
        tool_version="1.0",
        validated_arguments=arguments,
        display_summary={"summary": summary, "workflow_data": workflow_data},
    )
    conversation = await runtime.context.conversation_service.load_owned(
        state["conversation_id"], int(trusted["odoo_user_id"])
    )
    await runtime.context.conversation_service.update(
        conversation,
        status=ConversationStatus.AWAITING_CONFIRMATION,
        pending_tool_name=PROFILE_WORKFLOW,
        workflow_data={"pending_action_id": action.action_id},
    )
    approval = write_mode is ProfileWriteMode.APPROVAL_REQUEST
    action_label = {
        Operation.CREATE: "thêm",
        Operation.UPDATE: "cập nhật",
        Operation.DELETE: "xóa",
    }[operation]
    confirm_label = (
        "Gửi yêu cầu điều chỉnh" if approval
        else "Xác nhận xóa" if operation is Operation.DELETE
        else f"Xác nhận {action_label}"
    )
    cancel_label = "Không xóa" if operation is Operation.DELETE else "Hủy"
    text = (
        "Bạn có xác nhận gửi yêu cầu điều chỉnh không?"
        if approval else f"Bạn có xác nhận {action_label} thông tin không?"
    )
    confirmation = {
        "action_id": action.action_id,
        "action": operation.value,
        "title": (
            "Xác nhận gửi yêu cầu điều chỉnh"
            if approval else f"{action_label.capitalize()} {resource.label}"
        ),
        "summary": summary,
        "confirm_label": confirm_label,
        "cancel_label": cancel_label,
        "expires_at": action.expires_at.isoformat(),
    }
    update = stage_update(
        state, event="profile_confirmation_required",
        timing_name="pending_action_ms", started=started,
        data={"action_id": action.action_id, "operation": operation.value},
    )
    update.update({
        **workflow_data,
        "pending_action_id": action.action_id,
        "pending_tool_name": PROFILE_WORKFLOW,
        "workflow_data": workflow_data,
        "response_type": ChatResponseType.CONFIRMATION_REQUIRED,
        "response_text": text,
        "response_data": {
            "message_type": "confirmation",
            "text": text,
            "confirmation": confirmation,
        },
    })
    return update


def _match_records(records: tuple[Any, ...], reference: str | None) -> list[Any]:
    if not records:
        return []
    normalized = _normalized(reference or "")
    if not normalized:
        return list(records)
    recency_tokens = ("dong dau tien", "ban gan nhat", "moi nhat")
    if any(token in normalized for token in recency_tokens):
        return [records[0]]
    words = [word for word in normalized.split() if word not in {
        "sua", "xoa", "chung", "chi", "dong", "ban", "cap", "ngay"
    }]
    matches = []
    for record in records:
        snapshot_values = " ".join(
            _display_value(value) for value in record.snapshot.values()
        )
        date_aliases = " ".join(
            _date_aliases(value) for value in record.snapshot.values()
        )
        haystack = _normalized(
            " ".join(
                filter(
                    None,
                    [
                        record.label,
                        record.description or "",
                        snapshot_values,
                        date_aliases,
                    ],
                )
            )
        )
        all_words_match = words and all(word in haystack for word in words)
        if normalized in haystack or all_words_match:
            matches.append(record)
    return matches


def _record_options(records: list[Any]) -> list[dict[str, Any]]:
    return [{"value": str(item.record_id), "label": item.label,
             "description": item.description} for item in records]


def _date_aliases(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    parts = value[:10].split("-")
    if len(parts) != 3 or not all(part.isdigit() for part in parts):
        return ""
    year, month, day = (int(part) for part in parts)
    return f"{day}/{month} {day:02d}/{month:02d} {day}/{month}/{year}"


def _normalized(value: str) -> str:
    decomposed = unicodedata.normalize("NFD", str(value).casefold())
    return " ".join(
        "".join(character for character in decomposed
                if unicodedata.category(character) != "Mn")
        .replace("đ", "d").replace("·", " ").split()
    )


def _display_value(value: Any) -> str:
    if isinstance(value, dict):
        return str(value.get("label") or value.get("value") or "")
    if isinstance(value, list):
        return ", ".join(_display_value(item) for item in value)
    return "" if value is None else str(value)


def _same_value(current: Any, proposed: Any) -> bool:
    if isinstance(current, dict):
        current = current.get("value")
    if isinstance(proposed, dict):
        proposed = proposed.get("value")
    return str(current if current is not None else "") == str(
        proposed if proposed is not None else ""
    )


async def _clarify_section(
    state: ChatGraphState,
    runtime: Runtime[GraphContext],
    started: float,
    sections: tuple[Any, ...],
    classification: QueryClassification,
    operation: Operation,
    workflow_data: dict[str, Any],
    text: str,
) -> dict[str, object]:
    allowed = []
    schema = runtime.context.profile_schema_client
    actor = int(state["trusted_context"]["odoo_user_id"])
    for section in sections:
        resources = await schema.get_resources(
            section.key,
            operation,
            odoo_user_id=actor,
            request_id=state["request_id"],
        )
        if resources:
            allowed.append(section)
    return await _clarification(
        state,
        runtime,
        started,
        classification,
        operation,
        workflow_data,
        section_key=None,
        resource_key=None,
        field_keys=[],
        record_reference=None,
        changes={},
        slot_name="profile_section_key",
        input_type="section_select",
        text=text,
        options=_options(allowed),
    )


async def _clarify_value(
    state: ChatGraphState,
    runtime: Runtime[GraphContext],
    started: float,
    classification: QueryClassification,
    operation: Operation,
    workflow_data: dict[str, Any],
    resource: ProfileResource,
    field: ProfileField,
    field_keys: list[str],
    record_reference: str | None,
    changes: dict[str, Any],
    *,
    missing_profile_slots: list[str],
) -> dict[str, object]:
    current_mode = workflow_data.get("profile_write_mode")
    workflow_data = {
        **workflow_data,
        "profile_write_mode": (
            ProfileWriteMode.APPROVAL_REQUEST
            if field.write_mode is ProfileWriteMode.APPROVAL_REQUEST
            or current_mode == ProfileWriteMode.APPROVAL_REQUEST
            else ProfileWriteMode.DIRECT
        ),
    }
    options: list[dict[str, str | None]] = []
    input_type = input_type_for_field(field)
    if input_type in {"single_select", "searchable_select"}:
        registry_options = await (
            runtime.context.profile_schema_client.get_field_options(
                resource.key,
                field.key,
                odoo_user_id=int(state["trusted_context"]["odoo_user_id"]),
                request_id=state["request_id"],
            )
        )
        options = _options(registry_options)
    return await _clarification(
        state,
        runtime,
        started,
        classification,
        operation,
        workflow_data,
        section_key=resource.section_key,
        resource_key=resource.key,
        field_keys=field_keys,
        record_reference=record_reference,
        changes=changes,
        slot_name=field.key,
        input_type=input_type,
        text=f"Bạn muốn nhập {field.label} là gì?",
        options=options,
        missing_profile_slots=missing_profile_slots,
    )


async def _clarification(
    state: ChatGraphState,
    runtime: Runtime[GraphContext],
    started: float,
    classification: QueryClassification,
    operation: Operation,
    workflow_data: dict[str, Any],
    *,
    section_key: str | None,
    resource_key: str | None,
    field_keys: list[str],
    record_reference: str | None,
    changes: dict[str, Any],
    slot_name: str,
    input_type: str,
    text: str,
    options: list[dict[str, Any]],
    missing_profile_slots: list[str] | None = None,
) -> dict[str, object]:
    profile_data = _profile_data(
        section_key=section_key,
        resource_key=resource_key,
        field_keys=field_keys,
        record_reference=record_reference,
        changes=changes,
        write_mode=workflow_data.get("profile_write_mode"),
        missing_profile_slots=missing_profile_slots or [slot_name],
    )
    profile_data["profile_record_id"] = workflow_data.get("profile_record_id")
    clarification: dict[str, Any] = {
        "input_type": input_type,
        "slot_name": slot_name,
    }
    if options:
        clarification["options"] = options
    updated = {
        **workflow_data,
        **profile_data,
        "classification": classification.model_dump(mode="json"),
        "current_field": slot_name,
        "clarification_options": options,
        "clarification_metadata": clarification,
        "operation": operation.value,
    }
    conversation = await runtime.context.conversation_service.load_owned(
        state["conversation_id"],
        int(state["trusted_context"]["odoo_user_id"]),
    )
    await runtime.context.conversation_service.update(
        conversation,
        status=ConversationStatus.AWAITING_CLARIFICATION,
        pending_tool_name=PROFILE_WORKFLOW,
        collected_arguments=state.get("collected_arguments", {}),
        missing_arguments=[slot_name],
        ambiguous_arguments=[],
        workflow_data=updated,
        entity_memory=state.get("entity_memory", {}),
    )
    response_data = {
        "message_type": "clarification",
        "text": text,
        "clarification": clarification,
    }
    if workflow_data.get("profile_resolution_error"):
        response_data["error_code"] = workflow_data["profile_resolution_error"]
    update = stage_update(
        state,
        event="profile_clarification_required",
        timing_name="argument_resolution_ms",
        started=started,
        data={"slot_name": slot_name},
    )
    update.update(
        {
            **profile_data,
            "pending_tool_name": PROFILE_WORKFLOW,
            "missing_arguments": [slot_name],
            "workflow_data": updated,
            "response_type": ChatResponseType.CLARIFICATION_REQUIRED,
            "response_text": text,
            "response_data": response_data,
        }
    )
    return update


def _profile_data(
    *,
    section_key: str | None,
    resource_key: str | None,
    field_keys: list[str],
    record_reference: str | None,
    changes: dict[str, Any],
    write_mode: str | None,
    missing_profile_slots: list[str],
) -> dict[str, Any]:
    return {
        "profile_section_key": section_key,
        "profile_resource_key": resource_key,
        "profile_field_keys": field_keys,
        "profile_record_reference": record_reference,
        "profile_record_id": None,
        "profile_write_mode": write_mode,
        "profile_current_snapshot": {},
        "profile_changes": changes,
        "missing_profile_slots": missing_profile_slots,
    }


def _options(items: Any) -> list[dict[str, Any]]:
    return [
        {
            "value": str(getattr(item, "value", getattr(item, "key", ""))),
            "label": str(getattr(item, "label", "")),
            "description": getattr(item, "description", None),
        }
        for item in items
    ]


def _forbidden(
    state: ChatGraphState,
    started: float,
    description: str,
) -> dict[str, object]:
    text = "Thông tin này không thể thay đổi qua hồ sơ tự khai."
    if description and description not in text:
        text = f"{text} {description}"
    return _typed_error(
        state,
        started,
        "PROFILE_OPERATION_FORBIDDEN",
        text,
        CapabilityOutcome.DENIED,
    )


def _typed_error(
    state: ChatGraphState,
    started: float,
    code: str,
    text: str,
    outcome: CapabilityOutcome,
    *,
    workflow_data: dict[str, Any] | None = None,
) -> dict[str, object]:
    update = stage_update(
        state,
        event="profile_write_stopped",
        timing_name="argument_resolution_ms",
        started=started,
        data={"reason_code": code},
    )
    update.update(
        {
            "response_type": ChatResponseType.ERROR,
            "capability_outcome": outcome,
            "response_text": text,
            "response_data": {"error_code": code},
            "workflow_data": workflow_data or state.get("workflow_data", {}),
        }
    )
    return update


__all__ = ["PROFILE_WORKFLOW", "resolve_profile_write_node"]
