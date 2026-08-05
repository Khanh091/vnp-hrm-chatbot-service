from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import unicodedata
from time import perf_counter
from typing import Any
from uuid import uuid4

from langgraph.runtime import Runtime

from app.common.capability_outcomes import CapabilityOutcome
from app.context.conversation import ConversationStatus
from app.context.entity_memory import ConversationEntityMemory
from app.integrations.odoo.profile_schema import (
    ProfileField,
    ProfileResource,
    ProfileSchemaError,
    ProfileSection,
    ProfileWriteMode,
    input_type_for_field,
)
from app.orchestration.context import GraphContext
from app.orchestration.nodes.common import stage_update
from app.orchestration.state import ChatGraphState, ChatResponseType
from app.routing.profile_target_resolver import (
    ProfileTargetOutsideAllowlistError,
    ProfileTargetResolution,
    ProfileTargetResolverError,
)
from app.routing.schemas import QueryClassification
from app.routing.taxonomy import Operation

PROFILE_WORKFLOW = "profile_crud_workflow"
logger = logging.getLogger(__name__)


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
    answer_field = (
        structured_answer.get("field")
        if isinstance(structured_answer, dict) else None
    )
    change_labels = dict(workflow_data.get("profile_change_labels", {}))
    if (
        isinstance(structured_answer, dict)
        and structured_answer.get("answer_type") == "profile_field_edit"
        and answer_field
        and structured_answer.get("label") is not None
    ):
        change_labels[str(answer_field)] = str(structured_answer["label"])
    workflow_data["profile_change_labels"] = change_labels
    edit_action = (
        str(collected.get("profile_edit_action"))
        if answer_field == "profile_edit_action"
        and collected.get("profile_edit_action") is not None
        else None
    )
    workflow_data["profile_edit_action"] = edit_action
    if edit_action == "continue":
        workflow_data.pop("profile_deferred_query", None)
        if workflow_data.get("profile_edit_status") == "OVERRIDE_GUARD":
            workflow_data["profile_edit_status"] = "EDITING"
    if edit_action in {"switch_save_draft", "switch_discard"}:
        return await _resume_deferred_profile_query(
            state,
            runtime,
            started,
            workflow_data,
            save_draft=edit_action == "switch_save_draft",
        )

    if (
        isinstance(structured_answer, dict)
        and structured_answer.get("answer_type") == "option_select"
        and structured_answer.get("field")
        in {
            "profile_section_key",
            "profile_section_item",
            "profile_resource_key",
            "profile_field_keys",
            "profile_record_id",
            "derived_resource_action",
            "profile_edit_action",
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
            # Record selection opens the complete bounded record form.  The
            # user chooses the field there; do not auto-open the resolver's
            # first matching field.
            field_keys = []
            workflow_data["profile_field_keys"] = []
    elif isinstance(selected_record_id, str) and selected_record_id.strip():
        # A free-text follow-up is treated as a reference, never as an ORM id.
        record_reference = selected_record_id.strip()
        workflow_data["profile_record_reference"] = record_reference
    changes = dict(workflow_data.get("profile_changes", {}))
    for key in field_keys:
        if key in collected:
            changes[key] = collected[key]

    selected_derived_action = collected.get("derived_resource_action")
    if selected_derived_action in {"create", "update"}:
        derived_resource = workflow_data.get("derived_from_resource")
        if derived_resource:
            resource_key = str(derived_resource)
            field_keys = []
            operation = Operation(str(selected_derived_action))
            classification = classification.model_copy(
                update={"operation": operation}
            )
            workflow_data.update({
                "profile_resource_key": resource_key,
                "profile_field_keys": [],
                "operation": operation.value,
            })

    schema = runtime.context.profile_schema_client
    try:
        section_summaries = await schema.get_sections(
            None,
            odoo_user_id=actor,
            request_id=request_id,
        )
        sections = tuple(
            await asyncio.gather(
                *(
                    schema.get_section(
                        section.key,
                        None,
                        odoo_user_id=actor,
                        request_id=request_id,
                    )
                    for section in section_summaries
                )
            )
        )
        resource_summaries = [
            resource
            for group in await asyncio.gather(
                *(
                    schema.get_resources(
                        section.key,
                        None,
                        odoo_user_id=actor,
                        request_id=request_id,
                    )
                    for section in sections
                )
            )
            for resource in group
        ]
        all_resources = list(
            await asyncio.gather(
                *(
                    schema.get_resource(
                        resource.key,
                        odoo_user_id=actor,
                        request_id=request_id,
                    )
                    for resource in resource_summaries
                )
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
                    recent_profile_targets=[
                        {
                            "label": item.get("label"),
                            **item.get("attributes", {}),
                        }
                        for item in state.get("entity_memory", {}).get(
                            "last_profile_targets", []
                        )
                        if isinstance(item, dict)
                    ],
                    request_id=request_id,
                )
                (
                    section_key,
                    resource_key,
                    field_keys,
                    record_reference,
                ) = _merge_profile_target(
                    section_key,
                    resource_key,
                    field_keys,
                    record_reference,
                    resolution,
                )
                workflow_data["profile_resolution_reason"] = resolution.reason_code
                workflow_data["profile_candidate_counts"] = {
                    "sections": len(sections),
                    "resources": len(all_resources),
                    "fields": sum(len(item.direct_fields) for item in sections)
                    + sum(len(item.fields) for item in all_resources),
                }
                if resolution.needs_clarification and len(field_keys) > 1:
                    candidate_resource = next(
                        (
                            item for item in all_resources
                            if item.key == resource_key
                            and item.section_key == section_key
                        ),
                        None,
                    )
                    candidate_fields = (
                        [
                            item for item in candidate_resource.fields
                            if item.key in field_keys
                        ]
                        if candidate_resource is not None
                        else [
                            item
                            for candidate_section in sections
                            if candidate_section.key == section_key
                            for item in candidate_section.direct_fields
                            if item.key in field_keys
                        ]
                    )
                    return await _clarification(
                        state,
                        runtime,
                        started,
                        classification,
                        operation,
                        workflow_data,
                        section_key=section_key,
                        resource_key=resource_key,
                        field_keys=field_keys,
                        record_reference=record_reference,
                        changes=changes,
                        slot_name="profile_field_keys",
                        input_type="field_select",
                        text="Có nhiều thông tin phù hợp. Bạn muốn sửa mục nào?",
                        options=[
                            {
                                "value": item.key,
                                "label": item.label,
                                "description": item.description,
                            }
                            for item in candidate_fields
                        ],
                    )
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

        section = next(
            (item for item in sections if item.key == str(section_key)),
            None,
        )
        if section is None:
            raise ProfileTargetOutsideAllowlistError()

        selected_section_item = collected.get("profile_section_item")
        if (
            selected_section_item
            and isinstance(structured_answer, dict)
            and structured_answer.get("answer_type") == "option_select"
            and structured_answer.get("field") == "profile_section_item"
        ):
            selected_key = str(selected_section_item)
            direct = next(
                (item for item in section.direct_fields
                 if item.key == selected_key),
                None,
            )
            child = next(
                (item for item in all_resources
                 if item.section_key == section.key
                 and item.key == selected_key),
                None,
            )
            if direct is not None:
                resource_key = None
                field_keys = [direct.key]
            elif child is not None:
                resource_key = child.key
                field_keys = []
            else:
                raise ProfileTargetOutsideAllowlistError()
            workflow_data["profile_resource_key"] = resource_key
            workflow_data["profile_field_keys"] = field_keys

        direct_fields = [
            item for item in section.direct_fields if item.key in field_keys
        ]
        target_resource = next(
            (item for item in all_resources if item.key == resource_key), None
        )
        target_field = (
            direct_fields[0] if len(direct_fields) == 1 else
            next(
                (field for field in (target_resource.fields
                                     if target_resource else ())
                 if field.key in field_keys),
                None,
            )
        )
        target_label = (
            target_field.label if target_field else
            target_resource.label if target_resource else section.label
        )
        memory = runtime.context.entity_memory_service.capture(
            tool_name="profile_target",
            data={
                "section_key": section.key,
                "resource_key": resource_key,
                "field_key": target_field.key if target_field else None,
                "label": target_label,
            },
            memory=ConversationEntityMemory.model_validate(
                state.get("entity_memory", {})
            ),
        )
        state["entity_memory"] = memory.model_dump(mode="json")
        if direct_fields:
            if len(direct_fields) != len(field_keys) or resource_key is not None:
                raise ProfileTargetOutsideAllowlistError()
            return await _resolve_direct_field_update(
                state, runtime, started, classification, workflow_data,
                section, direct_fields, record_reference, changes,
            )

        if not resource_key:
            return await _clarification(
                state, runtime, started, classification, operation,
                workflow_data, section_key=str(section_key),
                resource_key=None, field_keys=[],
                record_reference=record_reference, changes=changes,
                slot_name="profile_section_item", input_type="field_select",
                text="Bạn muốn sửa mục nào?",
                options=_section_item_options(
                    section, all_resources, operation
                ),
            )

        resource = await schema.get_resource(
            str(resource_key),
            odoo_user_id=actor,
            request_id=request_id,
        )
        if resource.section_key != section_key:
            raise ProfileTargetOutsideAllowlistError()
        if operation is Operation.CREATE and resource.resource_type == "singleton":
            operation = Operation.UPDATE
            classification = classification.model_copy(
                update={"operation": operation}
            )
            workflow_data["operation"] = operation.value
        if not resource.allows(operation):
            return _forbidden(state, started, "")
        if edit_action and edit_action.startswith("edit:"):
            requested_field = edit_action.split(":", 1)[1]
            if requested_field not in {field.key for field in resource.fields}:
                raise ProfileTargetOutsideAllowlistError()
            field_keys = [requested_field]
            workflow_data["profile_field_keys"] = field_keys
        if edit_action == "continue":
            field_keys = []
            workflow_data["profile_field_keys"] = []

        # Follow-up answers are stored by canonical slot name. Merge every field
        # emitted by this bounded resource, not only the initially resolved keys.
        # Collection creates often start without field_keys, which previously made
        # a value such as "IELTS" disappear and caused the same question to repeat.
        previous_changes = dict(changes)
        applied_field_key = (
            str(answer_field) if answer_field in {item.key for item in resource.fields}
            else str(workflow_data.get("current_field") or "")
        )
        if applied_field_key not in {item.key for item in resource.fields}:
            supplied_keys = [
                item.key for item in resource.fields if item.key in collected
            ]
            applied_field_key = supplied_keys[0] if len(supplied_keys) == 1 else ""
        applied_definition = next(
            (item for item in resource.fields if item.key == applied_field_key),
            None,
        )
        if applied_definition is not None and applied_field_key in collected:
            applied_value = collected[applied_field_key]
            previous_value = previous_changes.get(
                applied_field_key,
                workflow_data.get("profile_current_snapshot", {}).get(
                    applied_field_key
                ),
            )
            changes[applied_field_key] = applied_value
            if not profile_values_equal(
                applied_definition, previous_value, applied_value
            ):
                _clear_invalid_dependents(
                    resource.fields, applied_field_key, changes, change_labels,
                    workflow_data.setdefault("profile_option_sets", {}),
                )

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
            if forbidden_field.derived_from_resource:
                return await _derived_redirect(
                    state, runtime, started, classification, workflow_data,
                    section_key=str(section_key), field=forbidden_field,
                    changes=changes,
                )
            return _forbidden(
                state,
                started,
                forbidden_field.restriction_reason
                or forbidden_field.description or "",
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
        current_field_key = workflow_data.get("current_field")
        previous_input_type = workflow_data.get(
            "clarification_metadata", {}
        ).get("input_type")
        if (
            current_field_key in collected
            and previous_input_type in {"single_select", "searchable_select"}
            and not (
                isinstance(structured_answer, dict)
                and structured_answer.get("answer_type") == "option_select"
                and structured_answer.get("field") == current_field_key
            )
        ):
            invalid_field = next(
                (item for item in resource.fields
                 if item.key == current_field_key),
                None,
            )
            if invalid_field is not None:
                changes.pop(invalid_field.key, None)
                return await _clarify_value(
                    state, runtime, started, classification, operation,
                    workflow_data, resource, invalid_field, field_keys,
                    record_reference, changes,
                    missing_profile_slots=[invalid_field.key],
                    error_message=(
                        f"Giá trị {collected[current_field_key]!r} chưa được "
                        f"chọn từ danh sách {invalid_field.label}. Vui lòng "
                        "chọn một lựa chọn bên dưới."
                    ),
                )
        if edit_action == "cancel":
            return await _cancel_edit_session(state, runtime, started)
        if edit_action and edit_action.startswith("edit:"):
            field = next(
                item for item in operation_fields if item.key == field_keys[0]
            )
            return await _clarify_value(
                state, runtime, started, classification, operation,
                workflow_data, resource, field, field_keys,
                record_reference, changes,
                missing_profile_slots=[field.key],
            )
        if operation is Operation.CREATE:
            for definition in operation_fields:
                if (
                    definition.default_value is not None
                    and definition.key not in changes
                ):
                    changes[definition.key] = definition.default_value
            required = [item for item in operation_fields if item.required_on_create]
            missing = [
                item for item in required
                if item.key not in changes
                or changes[item.key] in {None, ""}
            ]
            if edit_action != "finish":
                return await _profile_draft_form(
                    state, runtime, started, classification, operation,
                    workflow_data, resource, list(operation_fields),
                    record_reference, changes, {}, None,
                )
            if missing:
                labels = "\n".join(f"- {item.label}" for item in missing)
                return await _profile_draft_form(
                    state, runtime, started, classification, operation,
                    workflow_data, resource, list(operation_fields),
                    record_reference, changes, {}, None,
                    notice=(
                        "Vui lòng hoàn thiện các trường bắt buộc:\n" + labels
                    ),
                    missing_required=[item.key for item in missing],
                )
        elif operation is Operation.UPDATE:
            if not selected_fields and edit_action not in {
                "finish", "submit", "save_draft"
            }:
                selectable_fields = list(operation_fields)
                selectable_keys = {item.key for item in selectable_fields}
                selectable_fields.extend(
                    item for item in resource.fields
                    if item.derived_from_resource
                    and item.key not in selectable_keys
                )
                current = (
                    await schema.get_current_snapshot(
                        resource.key, odoo_user_id=actor,
                        request_id=request_id,
                    )
                    if resource.resource_type == "singleton"
                    else await schema.get_record(
                        resource.key, int(record_id), odoo_user_id=actor,
                        request_id=request_id,
                    )
                )
                return await _profile_draft_form(
                    state, runtime, started, classification, operation,
                    workflow_data, resource, selectable_fields,
                    record_reference, changes, dict(current.snapshot),
                    current.version,
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
            definitions = {item.key: item for item in resource.fields}
            changes = {
                key: value for key, value in changes.items()
                if key in definitions and not profile_values_equal(
                    definitions[key], current_snapshot.get(key), value
                )
            }
            if not changes:
                return await _profile_draft_form(
                    state, runtime, started, classification, operation,
                    workflow_data, resource, list(operation_fields),
                    record_reference, {}, current_snapshot,
                    expected_version,
                    notice="Không có thay đổi nào để hoàn tất.",
                    allow_finish=False,
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
        if operation is Operation.DELETE:
            return await _create_profile_confirmation(
                state, runtime, started, classification, resource, operation,
                selected_fields, record_id, current_snapshot,
                expected_version, changes, write_mode, workflow_data,
            )
        draft_fields = selected_fields or list(operation_fields)
        option_errors = await _validate_current_option_sets(
            state, runtime, resource, draft_fields, changes, workflow_data
        ) if edit_action in {"finish", "save_draft", "submit"} else {}
        field_errors = _validate_profile_fields(
            draft_fields, changes, operation=operation
        )
        field_errors = {**option_errors, **field_errors}
        if field_errors and edit_action in {"finish", "save_draft", "submit"}:
            return await _profile_draft_form(
                state, runtime, started, classification, operation,
                workflow_data, resource, list(operation_fields),
                record_reference, changes, current_snapshot, expected_version,
                notice=next(iter(field_errors.values())),
                missing_required=list(field_errors),
            )
        if edit_action == "submit":
            return await _create_profile_confirmation(
                state, runtime, started, classification, resource, operation,
                draft_fields, record_id, current_snapshot,
                expected_version, changes, write_mode, workflow_data,
            )
        if edit_action == "save_draft":
            return await _save_profile_draft(
                state, runtime, started, classification, resource, operation,
                record_id, expected_version, changes, workflow_data,
            )
        if edit_action == "finish" and not changes:
            return await _profile_draft_form(
                state, runtime, started, classification, operation,
                workflow_data, resource, list(operation_fields),
                record_reference, changes, current_snapshot,
                expected_version,
                notice="Không có thay đổi nào để hoàn tất.",
                allow_finish=False,
            )
        if edit_action == "finish":
            return await _profile_edit_summary(
                state, runtime, started, classification, resource, operation,
                draft_fields, record_id, current_snapshot,
                expected_version, changes, write_mode, workflow_data,
            )
        return await _profile_draft_form(
            state, runtime, started, classification, operation,
            workflow_data, resource, list(operation_fields),
            record_reference, changes, current_snapshot, expected_version,
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
            "PROFILE_DRAFT_EMPTY": "Bản nháp chưa có thay đổi để lưu.",
            "PROFILE_DRAFT_SAVE_FAILED": (
                "Odoo chưa xác nhận dữ liệu bản nháp sau khi tải lại. "
                "Các thay đổi trong phiên vẫn được giữ để thử lại."
            ),
            "PROFILE_DRAFT_VERSION_CONFLICT": (
                "Hồ sơ tự khai đã thay đổi ở nơi khác. Vui lòng tải lại trước khi lưu."
            ),
            "PROFILE_EDIT_SESSION_INVALID_STATE": (
                "Hồ sơ tự khai hiện không ở trạng thái cho phép chỉnh sửa."
            ),
            "PROFILE_OPTION_SET_STALE": (
                "Danh sách lựa chọn đã thay đổi. Vui lòng chọn lại."
            ),
            "PROFILE_OPTION_NOT_ALLOWED": (
                "Lựa chọn không hợp lệ trong ngữ cảnh hiện tại."
            ),
            "PROFILE_DEPENDENCY_CHANGED": (
                "Trường phụ thuộc đã thay đổi. Vui lòng chọn lại."
            ),
            "PROFILE_REQUIRED_FIELD_MISSING": (
                "Vui lòng hoàn thiện các trường bắt buộc."
            ),
            "PROFILE_DATE_RANGE_INVALID": "Khoảng ngày không hợp lệ.",
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


async def _resolve_direct_field_update(
    state: ChatGraphState,
    runtime: Runtime[GraphContext],
    started: float,
    classification: QueryClassification,
    workflow_data: dict[str, Any],
    section: ProfileSection,
    selected_fields: list[ProfileField],
    record_reference: str | None,
    changes: dict[str, Any],
) -> dict[str, object]:
    operation = Operation.UPDATE
    classification = classification.model_copy(update={"operation": operation})
    collected = dict(state.get("collected_arguments", {}))
    structured_answer = state.get("clarification")
    answer_field = (
        structured_answer.get("field")
        if isinstance(structured_answer, dict) else None
    )
    applied_key = (
        str(answer_field)
        if answer_field in {item.key for item in section.direct_fields}
        else str(workflow_data.get("current_field") or "")
    )
    if applied_key in collected:
        changes[applied_key] = collected[applied_key]

    forbidden = next(
        (field for field in selected_fields if not field.updatable), None
    )
    if forbidden is not None:
        if forbidden.derived_from_resource:
            return await _derived_redirect(
                state, runtime, started, classification, workflow_data,
                section_key=section.key, field=forbidden, changes=changes,
            )
        return _forbidden(
            state, started,
            forbidden.restriction_reason or forbidden.description or "",
        )

    actor = int(state["trusted_context"]["odoo_user_id"])
    current = await runtime.context.profile_schema_client.get_section_snapshot(
        section.key, odoo_user_id=actor, request_id=state["request_id"]
    )
    current_snapshot = dict(current.snapshot)
    current_field_key = workflow_data.get("current_field")
    previous_input_type = workflow_data.get(
        "clarification_metadata", {}
    ).get("input_type")
    if (
        current_field_key in collected
        and previous_input_type in {"single_select", "searchable_select"}
        and not (
            isinstance(structured_answer, dict)
            and structured_answer.get("answer_type") == "option_select"
            and structured_answer.get("field") == current_field_key
        )
    ):
        invalid_field = next(
            (item for item in selected_fields if item.key == current_field_key),
            None,
        )
        if invalid_field is not None:
            changes.pop(invalid_field.key, None)
            return await _clarify_direct_value(
                state, runtime, started, classification, workflow_data,
                section, invalid_field, [invalid_field.key],
                record_reference, changes, current_snapshot=current_snapshot,
                missing_profile_slots=[invalid_field.key],
                error_message=(
                    f"Giá trị {collected[current_field_key]!r} chưa được "
                    f"chọn từ danh sách {invalid_field.label}. Vui lòng "
                    "chọn một lựa chọn bên dưới."
                ),
            )
    edit_action = workflow_data.get("profile_edit_action")
    if edit_action and str(edit_action).startswith("edit:"):
        requested_key = str(edit_action).split(":", 1)[1]
        field = next(
            (item for item in selected_fields if item.key == requested_key),
            None,
        )
        if field is None:
            raise ProfileTargetOutsideAllowlistError()
        return await _clarify_direct_value(
            state, runtime, started, classification, workflow_data,
            section, field, [field.key], record_reference, changes,
            current_snapshot=current_snapshot,
            missing_profile_slots=[field.key],
        )
    missing = [field for field in selected_fields if field.key not in changes]
    if missing:
        return await _clarify_direct_value(
            state, runtime, started, classification, workflow_data,
            section, missing[0], [field.key for field in selected_fields],
            record_reference, changes,
            current_snapshot=current_snapshot,
            missing_profile_slots=[field.key for field in missing],
        )

    definitions = {item.key: item for item in section.direct_fields}
    changes = {
        key: value for key, value in changes.items()
        if key in definitions and not profile_values_equal(
            definitions[key], current_snapshot.get(key), value
        )
    }
    if not changes:
        return await _direct_draft_form(
            state, runtime, started, classification, workflow_data,
            section, selected_fields, record_reference, {},
            current_snapshot, current.version,
            notice="Giá trị bạn chọn không thay đổi; bản nháp chưa có cập nhật mới.",
        )
    write_mode = (
        ProfileWriteMode.APPROVAL_REQUEST
        if any(field.write_mode is ProfileWriteMode.APPROVAL_REQUEST
               for field in selected_fields)
        else ProfileWriteMode.DIRECT
    )
    profile_data = _profile_data(
        section_key=section.key, resource_key=None,
        field_keys=[field.key for field in selected_fields],
        record_reference=record_reference, changes=changes,
        write_mode=write_mode, missing_profile_slots=[],
    )
    profile_data["profile_current_snapshot"] = current_snapshot
    workflow_data.update(profile_data)
    workflow_data["operation"] = operation.value
    if edit_action == "cancel":
        return await _cancel_edit_session(state, runtime, started)
    if edit_action == "submit":
        return await _create_profile_confirmation(
            state, runtime, started, classification, None, operation,
            selected_fields, None, current_snapshot, current.version,
            changes, write_mode, workflow_data, section=section,
        )
    if edit_action == "save_draft":
        return await _save_profile_draft(
            state, runtime, started, classification, None, operation,
            None, current.version, changes, workflow_data, section=section,
        )
    if edit_action == "finish":
        return await _profile_edit_summary(
            state, runtime, started, classification, None, operation,
            selected_fields, None, current_snapshot, current.version,
            changes, write_mode, workflow_data, section=section,
        )
    return await _direct_draft_form(
        state, runtime, started, classification, workflow_data,
        section, selected_fields, record_reference, changes,
        current_snapshot, current.version,
    )


def _draft_field_rows(
    fields: list[ProfileField], current_snapshot: dict[str, Any],
    changes: dict[str, Any],
    operation: Operation = Operation.UPDATE,
    missing_required: set[str] | None = None,
    draft_labels: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    rows = []
    draft_labels = draft_labels or {}
    for field in fields:
        current = current_snapshot.get(field.key)
        draft_display = draft_labels.get(
            field.key, _display_value(changes.get(field.key))
        )
        changed = field.key in changes and not profile_values_equal(
            field, current, changes[field.key]
        )
        embedded_options = _options(field.selection_values)
        rows.append({
            "field_key": field.key,
            "label": field.label,
            "current_value": _display_value(current),
            "current_raw_value": current,
            "draft_value": (
                draft_display if field.key in changes
                else None
            ),
            "draft_raw_value": changes.get(field.key),
            "display_value": (
                f"{_display_value(current) or '—'} → "
                f"{draft_display or '—'}"
                if changed else (_display_value(current) or "—")
            ),
            "status": (
                "invalid" if field.key in (missing_required or set())
                else "changed" if changed else "unchanged"
            ),
            "input_type": input_type_for_field(field),
            "description": field.description,
            "required": field.required_on_create and operation is Operation.CREATE,
            "readonly": not field.allows(operation),
            "options": embedded_options,
            "option_set_id": (
                _embedded_option_set_id(field, embedded_options)
                if embedded_options else None
            ),
            "depends_on": list(field.depends_on),
            "options_context_keys": list(field.options_context_keys),
            "range_group": field.range_group,
            "clear_when_dependency_changes": field.clear_when_dependency_changes,
            "validation_error": (
                "Trường bắt buộc"
                if field.key in (missing_required or set()) else None
            ),
        })
    return rows


async def _profile_draft_form(
    state: ChatGraphState,
    runtime: Runtime[GraphContext],
    started: float,
    classification: QueryClassification,
    operation: Operation,
    workflow_data: dict[str, Any],
    resource: ProfileResource,
    fields: list[ProfileField],
    record_reference: str | None,
    changes: dict[str, Any],
    current_snapshot: dict[str, Any],
    expected_version: str | None,
    *,
    notice: str | None = None,
    allow_finish: bool = True,
    missing_required: list[str] | None = None,
) -> dict[str, object]:
    editable = [field for field in fields if field.allows(operation)]
    options = []
    if allow_finish:
        options.append({"value": "finish", "label": "Hoàn tất",
                        "description": None})
    else:
        options.append({"value": "continue", "label": "Tiếp tục chỉnh sửa",
                        "description": None})
    options.append({"value": "cancel", "label": "Hủy",
                    "description": None})
    workflow_data.update({
        "profile_current_snapshot": current_snapshot,
        "profile_expected_version": expected_version,
        "profile_changes": changes,
        "profile_edit_status": "EDITING",
        "profile_edit_session_id": workflow_data.get(
            "profile_edit_session_id"
        ) or f"profile-{uuid4()}",
        "profile_form_field_keys": [field.key for field in editable],
        "profile_form_revision": f"form-{uuid4()}",
    })
    return await _clarification(
        state, runtime, started, classification, operation, workflow_data,
        section_key=resource.section_key, resource_key=resource.key,
        field_keys=[], record_reference=record_reference, changes=changes,
        slot_name="profile_edit_action",
        input_type=("record_form" if resource.resource_type == "collection"
                    else "resource_form"),
        text=notice or "Bạn có thể tiếp tục chỉnh sửa hoặc bấm Hoàn tất.",
        options=options,
        extra_metadata={
            "title": resource.label,
            "fields": _draft_field_rows(
                list(resource.fields), current_snapshot, changes, operation,
                set(missing_required or []),
                workflow_data.get("profile_change_labels"),
            ),
            "status": "EDITING",
            "session_id": workflow_data["profile_edit_session_id"],
            "form_revision": workflow_data["profile_form_revision"],
            "mode": operation.value,
            "section_key": resource.section_key,
            "resource_key": resource.key,
            "record_token": (
                str(workflow_data.get("profile_record_id"))
                if workflow_data.get("profile_record_id") is not None else None
            ),
            "draft_count": sum(
                not profile_values_equal(
                    next(
                        item for item in resource.fields if item.key == key
                    ),
                    current_snapshot.get(key), value,
                )
                for key, value in changes.items()
                if key in {item.key for item in resource.fields}
            ),
        },
    )


async def _direct_draft_form(
    state: ChatGraphState,
    runtime: Runtime[GraphContext],
    started: float,
    classification: QueryClassification,
    workflow_data: dict[str, Any],
    section: ProfileSection,
    fields: list[ProfileField],
    record_reference: str | None,
    changes: dict[str, Any],
    current_snapshot: dict[str, Any],
    expected_version: str | None,
    *,
    notice: str | None = None,
    allow_finish: bool = True,
) -> dict[str, object]:
    options = []
    if changes and allow_finish:
        options.append({"value": "finish", "label": "Hoàn tất",
                        "description": None})
    options.extend((
        {"value": f"edit:{fields[0].key}", "label": "Sửa lại",
         "description": None},
        {"value": "cancel", "label": "Hủy", "description": None},
    ))
    workflow_data.update({
        "profile_current_snapshot": current_snapshot,
        "profile_expected_version": expected_version,
        "profile_changes": changes,
        "profile_edit_status": "EDITING",
        "profile_edit_session_id": workflow_data.get(
            "profile_edit_session_id"
        ) or f"profile-{uuid4()}",
        "profile_form_revision": f"form-{uuid4()}",
        "profile_form_field_keys": [field.key for field in fields],
    })
    return await _clarification(
        state, runtime, started, classification, Operation.UPDATE,
        workflow_data, section_key=section.key, resource_key=None,
        field_keys=[field.key for field in fields],
        record_reference=record_reference, changes=changes,
        slot_name="profile_edit_action", input_type="edit_summary",
        text=notice or "Thay đổi đang ở bản nháp. Bạn muốn làm gì tiếp?",
        options=options,
        extra_metadata={
            "title": fields[0].label,
            "fields": _draft_field_rows(
                fields, current_snapshot, changes,
                draft_labels=workflow_data.get("profile_change_labels"),
            ),
            "status": "EDITING",
            "session_id": workflow_data["profile_edit_session_id"],
            "form_revision": workflow_data["profile_form_revision"],
        },
    )


async def _profile_edit_summary(
    state: ChatGraphState,
    runtime: Runtime[GraphContext],
    started: float,
    classification: QueryClassification,
    resource: ProfileResource | None,
    operation: Operation,
    fields: list[ProfileField],
    record_id: int | None,
    current_snapshot: dict[str, Any],
    expected_version: str | None,
    changes: dict[str, Any],
    write_mode: ProfileWriteMode,
    workflow_data: dict[str, Any],
    *,
    section: ProfileSection | None = None,
    notice: str | None = None,
) -> dict[str, object]:
    workflow_data.update({
        "profile_current_snapshot": current_snapshot,
        "profile_expected_version": expected_version,
        "profile_changes": changes,
        "profile_record_id": record_id,
        "profile_edit_status": "REVIEWING",
        "profile_edit_session_id": workflow_data.get(
            "profile_edit_session_id"
        ) or f"profile-{uuid4()}",
        "profile_form_revision": f"form-{uuid4()}",
    })
    return await _clarification(
        state, runtime, started, classification, operation, workflow_data,
        section_key=(section.key if section else resource.section_key),
        resource_key=(resource.key if resource else None),
        field_keys=[field.key for field in fields if field.key in changes],
        record_reference=None, changes=changes,
        slot_name="profile_edit_action", input_type="edit_session_actions",
        text=notice or "Hãy chọn lưu nháp hoặc gửi xác nhận.",
        options=[
            {"value": "save_draft", "label": "Lưu nháp", "description": None},
            {"value": "submit", "label": "Gửi xác nhận", "description": None},
            {"value": "continue", "label": "Tiếp tục chỉnh sửa", "description": None},
            {"value": "cancel", "label": "Hủy thay đổi", "description": None},
        ],
        extra_metadata={
            "title": resource.label if resource else section.label,
            "fields": _draft_field_rows(
                [field for field in fields if field.key in changes],
                current_snapshot, changes, operation,
                draft_labels=workflow_data.get("profile_change_labels"),
            ),
            "status": "REVIEWING",
            "write_mode": write_mode.value,
            "session_id": workflow_data["profile_edit_session_id"],
            "form_revision": workflow_data["profile_form_revision"],
            "mode": operation.value,
            "section_key": section.key if section else resource.section_key,
            "resource_key": resource.key if resource else None,
        },
    )


async def _save_profile_draft(
    state: ChatGraphState,
    runtime: Runtime[GraphContext],
    started: float,
    classification: QueryClassification,
    resource: ProfileResource | None,
    operation: Operation,
    record_id: int | None,
    expected_version: str | None,
    changes: dict[str, Any],
    workflow_data: dict[str, Any],
    *,
    section: ProfileSection | None = None,
) -> dict[str, object]:
    action_key = (
        workflow_data.get("profile_last_client_action_id")
        or state["request_id"]
    )
    payload = {
        "section_key": section.key if section else None,
        "resource_key": resource.key if resource else None,
        "operation": operation.value,
        "record_id": record_id,
        "changes": changes,
        "expected_version": expected_version,
        "idempotency_key": (
            f"draft:{state['conversation_id']}:"
            f"{workflow_data.get('profile_edit_session_id')}:"
            f"{action_key}"
        ),
    }
    payload = {key: value for key, value in payload.items()
               if value is not None}
    try:
        result = await runtime.context.profile_schema_client.save_draft(
            payload,
            odoo_user_id=int(state["trusted_context"]["odoo_user_id"]),
            request_id=state["request_id"],
        )
    except ProfileSchemaError as error:
        if error.reason_code != "PROFILE_INVALID_VALUE":
            raise
        # An ORM constraint may reject a validly shaped canonical payload (for
        # example a start date later than its corresponding official date).
        # Keep the edit session alive and re-emit its actions so the user can
        # correct or cancel the draft instead of being left in a dead dialog.
        candidate_fields = list(
            section.direct_fields if section is not None else resource.fields
        )
        draft_fields = [
            field for field in candidate_fields if field.key in changes
        ] or candidate_fields
        current_snapshot = dict(
            workflow_data.get("profile_current_snapshot") or {}
        )
        detail = str(error).strip().rstrip(".")
        notice = (
            f"Không thể lưu bản nháp: {detail}. "
            "Các thay đổi vẫn được giữ; hãy sửa thông tin chưa hợp lệ rồi "
            "bấm Hoàn tất, hoặc hủy thay đổi."
        )
        workflow_data["profile_save_error"] = {
            "code": error.reason_code,
            "message": detail,
        }
        if section is not None:
            return await _direct_draft_form(
                state, runtime, started, classification, workflow_data,
                section, draft_fields, None, changes, current_snapshot,
                expected_version, notice=notice,
            )
        return await _profile_draft_form(
            state, runtime, started, classification, operation,
            workflow_data, resource, list(resource.fields), None, changes,
            current_snapshot, expected_version, notice=notice,
        )
    if result.draft_saved is not True:
        raise ProfileSchemaError(
            "PROFILE_DRAFT_SAVE_FAILED",
            "Odoo did not acknowledge a persisted draft",
        )
    await _verify_saved_draft(
        state, runtime, section, resource, operation, record_id, changes, result
    )
    logger.info(
        "profile_edit_action conversation_id=%s session_id=%s action_type=save_draft "
        "resource_key=%s state_before=REVIEWING state_after=DRAFT_SAVED "
        "draft_field_count=%s odoo_endpoint=%s result_code=SUCCESS",
        state["conversation_id"], workflow_data.get("profile_edit_session_id"),
        resource.key if resource else section.key if section else None,
        len(changes), "/api/hrm-chatbot/v1/profile/drafts",
    )
    conversation = await runtime.context.conversation_service.load_owned(
        state["conversation_id"],
        int(state["trusted_context"]["odoo_user_id"]),
    )
    await runtime.context.conversation_service.update(
        conversation, status=ConversationStatus.COMPLETED,
        pending_tool_name=None, collected_arguments={},
        missing_arguments=[], ambiguous_arguments=[], workflow_data={},
    )
    text = result.message or (
        "Các thay đổi đã được lưu vào hồ sơ tự khai nhưng chưa gửi phê duyệt."
    )
    update = stage_update(
        state, event="profile_draft_saved", timing_name="profile_draft_ms",
        started=started,
    )
    update.update({
        "response_type": ChatResponseType.ANSWER,
        "response_text": text,
        "response_data": {"message_type": "answer", "text": text,
                          "draft_saved": True},
        "workflow_data": {},
        "missing_arguments": [],
        "pending_tool_name": None,
    })
    return update


async def _verify_saved_draft(
    state, runtime, section, resource, operation, record_id, changes, result
):
    actor = int(state["trusted_context"]["odoo_user_id"])
    request_id = state["request_id"]
    definitions = {
        item.key: item
        for item in (section.direct_fields if section is not None else resource.fields)
    }
    if section is not None:
        reloaded = await runtime.context.profile_schema_client.get_section_snapshot(
            section.key, odoo_user_id=actor, request_id=request_id
        )
        snapshot = reloaded.snapshot
    elif resource.resource_type == "singleton":
        reloaded = await runtime.context.profile_schema_client.get_current_snapshot(
            resource.key, odoo_user_id=actor, request_id=request_id
        )
        snapshot = reloaded.snapshot
    else:
        verified_record_id = result.record_id or record_id
        if not verified_record_id:
            raise ProfileSchemaError(
                "PROFILE_DRAFT_SAVE_FAILED",
                "Odoo draft response did not include the edition record token",
            )
        reloaded = await runtime.context.profile_schema_client.get_record(
            resource.key, int(verified_record_id),
            odoo_user_id=actor, request_id=request_id,
        )
        snapshot = reloaded.snapshot
    mismatches = [
        key for key, value in changes.items()
        if key not in definitions
        or not profile_values_equal(definitions[key], snapshot.get(key), value)
    ]
    if mismatches:
        raise ProfileSchemaError(
            "PROFILE_DRAFT_SAVE_FAILED",
            "Reloaded edition draft does not contain the accepted changes",
        )


async def _resume_deferred_profile_query(
    state: ChatGraphState,
    runtime: Runtime[GraphContext],
    started: float,
    workflow_data: dict[str, Any],
    *,
    save_draft: bool,
) -> dict[str, object]:
    deferred_query = str(workflow_data.get("profile_deferred_query") or "").strip()
    if not deferred_query:
        return _typed_error(
            state,
            started,
            "PROFILE_DEFERRED_QUERY_MISSING",
            "Không còn tìm thấy câu hỏi mới. Các thay đổi vẫn được giữ.",
            CapabilityOutcome.INVALID,
        )
    if save_draft:
        payload = {
            "section_key": workflow_data.get("profile_section_key"),
            "resource_key": workflow_data.get("profile_resource_key"),
            "operation": workflow_data.get("operation") or "update",
            "record_id": workflow_data.get("profile_record_id"),
            "changes": dict(workflow_data.get("profile_changes") or {}),
            "expected_version": workflow_data.get("profile_expected_version"),
            "idempotency_key": (
                f"draft-switch:{state['conversation_id']}:{state['request_id']}"
            ),
        }
        payload = {key: value for key, value in payload.items() if value is not None}
        try:
            await runtime.context.profile_schema_client.save_draft(
                payload,
                odoo_user_id=int(state["trusted_context"]["odoo_user_id"]),
                request_id=state["request_id"],
            )
        except ProfileSchemaError as error:
            return _typed_error(
                state,
                started,
                error.reason_code,
                "Không thể lưu bản nháp; các thay đổi vẫn được giữ.",
                CapabilityOutcome.INVALID,
            )
    await runtime.context.conversation_service.clear_active_workflow(
        state["conversation_id"],
        int(state["trusted_context"]["odoo_user_id"]),
    )
    notice = (
        "Các thay đổi đã được lưu nháp và chưa gửi phê duyệt."
        if save_draft
        else "Các thay đổi nháp đã được bỏ."
    )
    update = stage_update(
        state,
        event="profile_deferred_query_resumed",
        timing_name="profile_edit_ms",
        started=started,
        data={"draft_saved": save_draft},
    )
    update.update({
        "user_message": deferred_query,
        "resume_deferred_query": True,
        "deferred_notice": notice,
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
        "response_type": None,
        "response_text": None,
        "response_data": None,
    })
    return update


async def _cancel_edit_session(
    state: ChatGraphState,
    runtime: Runtime[GraphContext],
    started: float,
) -> dict[str, object]:
    conversation = await runtime.context.conversation_service.load_owned(
        state["conversation_id"],
        int(state["trusted_context"]["odoo_user_id"]),
    )
    await runtime.context.conversation_service.update(
        conversation, status=ConversationStatus.CANCELLED,
        pending_tool_name=None, collected_arguments={},
        missing_arguments=[], ambiguous_arguments=[], workflow_data={},
    )
    text = "Đã hủy các thay đổi nháp trong cuộc trò chuyện."
    update = stage_update(
        state, event="profile_edit_cancelled", timing_name="profile_edit_ms",
        started=started,
    )
    update.update({
        "response_type": ChatResponseType.ANSWER,
        "response_text": text,
        "response_data": {"message_type": "answer", "text": text},
        "workflow_data": {}, "missing_arguments": [],
        "pending_tool_name": None,
    })
    return update


async def _create_profile_confirmation(
    state: ChatGraphState,
    runtime: Runtime[GraphContext],
    started: float,
    classification: QueryClassification,
    resource: ProfileResource | None,
    operation: Operation,
    selected_fields: list[ProfileField],
    record_id: int | None,
    current_snapshot: dict[str, Any],
    expected_version: str | None,
    changes: dict[str, Any],
    write_mode: ProfileWriteMode,
    workflow_data: dict[str, Any],
    *,
    section: ProfileSection | None = None,
) -> dict[str, object]:
    trusted = state["trusted_context"]
    action_key = (
        workflow_data.get("profile_last_client_action_id")
        or state["request_id"]
    )
    arguments = {
        "intent": classification.intent.value,
        "operation": operation.value,
        "section_key": section.key if section is not None else None,
        "resource_key": resource.key if resource is not None else None,
        "record_id": record_id,
        "current_snapshot": current_snapshot,
        "expected_version": expected_version,
        "changes": changes,
        "write_mode": write_mode.value,
        "idempotency_key": (
            f"submit:{state['conversation_id']}:"
            f"{workflow_data.get('profile_edit_session_id')}:"
            f"{action_key}"
        ),
    }
    arguments = {key: value for key, value in arguments.items() if value is not None}
    change_labels = workflow_data.get("profile_change_labels", {})
    summary = []
    for definition in selected_fields:
        if definition.key in changes:
            summary.append({
                "label": definition.label,
                "old_value": _display_value(current_snapshot.get(definition.key)),
                "new_value": change_labels.get(
                    definition.key, _display_value(changes[definition.key])
                ),
            })
    if operation is Operation.CREATE:
        if resource is None:
            raise ProfileTargetOutsideAllowlistError()
        fields_by_key = {field.key: field for field in resource.fields}
        summary = [
            {"label": fields_by_key[key].label, "old_value": None,
             "new_value": change_labels.get(key, _display_value(value))}
            for key, value in changes.items() if key in fields_by_key
        ]
    elif operation is Operation.DELETE:
        if resource is None:
            raise ProfileTargetOutsideAllowlistError()
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
        display_summary={
            "summary": summary,
            "workflow_data": workflow_data,
            "review": {
                "input_type": "edit_session_actions",
                "slot_name": "profile_edit_action",
                "title": resource.label if resource else section.label,
                "fields": _draft_field_rows(
                    [item for item in selected_fields if item.key in changes],
                    current_snapshot, changes, operation,
                    draft_labels=change_labels,
                ),
                "status": "REVIEWING",
                "session_id": workflow_data.get("profile_edit_session_id"),
                "mode": operation.value,
                "section_key": section.key if section else resource.section_key,
                "resource_key": resource.key if resource else None,
            },
        },
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
    target_label = resource.label if resource is not None else (
        selected_fields[0].label if len(selected_fields) == 1
        else section.label if section is not None else "hồ sơ"
    )
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
            if approval else f"{action_label.capitalize()} {target_label}"
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
    if isinstance(value, str):
        parts = value[:10].split("-")
        if len(parts) == 3 and all(part.isdigit() for part in parts):
            year, month, day = parts
            return f"{day}/{month}/{year}"
    return "" if value is None else str(value)


def profile_values_equal(
    field: ProfileField, current: Any, proposed: Any
) -> bool:
    """Compare canonical values; display labels never create a profile diff."""
    current = _canonical_profile_value(field, current)
    proposed = _canonical_profile_value(field, proposed)
    return current == proposed


def _canonical_profile_value(field: ProfileField, value: Any) -> Any:
    if isinstance(value, dict):
        value = value.get("value")
    if field.field_type == "many2many":
        values = (
            value if isinstance(value, list)
            else ([] if value is None else [value])
        )
        normalized = []
        for item in values:
            if isinstance(item, dict):
                item = item.get("value")
            if item not in (None, "", False):
                normalized.append(str(item))
        return tuple(sorted(normalized))
    if value in (None, ""):
        return None
    if field.field_type in {"many2one", "selection"}:
        return str(value)
    if field.field_type == "boolean":
        if isinstance(value, str):
            return value.strip().casefold() in {"1", "true", "yes", "có"}
        return bool(value)
    if field.field_type == "integer":
        try:
            return int(value)
        except (TypeError, ValueError):
            return value
    if field.field_type == "decimal":
        try:
            return float(value)
        except (TypeError, ValueError):
            return value
    if field.field_type in {"phone", "email"}:
        compact = str(value).strip().casefold()
        return "".join(compact.split())
    if field.field_type in {"text", "long_text"}:
        return str(value).strip()
    if field.field_type == "date":
        return str(value)[:10]
    return value


def _clear_invalid_dependents(
    fields, changed_key, changes, labels, option_sets
) -> None:
    pending = [changed_key]
    while pending:
        dependency = pending.pop()
        for field in fields:
            if (
                dependency in field.depends_on
                and field.clear_when_dependency_changes
            ):
                had_value = field.key in changes
                changes.pop(field.key, None)
                labels.pop(field.key, None)
                option_sets.pop(field.key, None)
                if had_value:
                    pending.append(field.key)


def _validate_profile_fields(fields, changes, *, operation):
    errors = {}
    if operation is Operation.CREATE:
        for field in fields:
            if field.required_on_create and changes.get(field.key) in (None, ""):
                errors[field.key] = f"Vui lòng nhập {field.label}."
    for field in fields:
        validator = field.validator or ""
        if not validator.startswith("gte:"):
            continue
        start_key = validator.split(":", 1)[1]
        start = changes.get(start_key)
        end = changes.get(field.key)
        if start in (None, "") or end in (None, ""):
            continue
        if str(start)[:10] > str(end)[:10]:
            errors[field.key] = (
                f"{field.label} phải bằng hoặc sau trường bắt đầu."
            )
    return errors


async def _validate_current_option_sets(
    state, runtime, resource, fields, changes, workflow_data
):
    stored = workflow_data.get("profile_option_sets", {})
    definitions = {item.key: item for item in fields}
    errors = {}
    for key, issued in stored.items():
        field = definitions.get(key)
        if field is None or key not in changes or not field.option_provider:
            continue
        context = {}
        for dependency in field.options_context_keys:
            value = changes.get(
                dependency,
                workflow_data.get("profile_current_snapshot", {}).get(dependency),
            )
            if isinstance(value, dict):
                value = value.get("value")
            if value not in (None, ""):
                context[dependency] = value
        if issued.get("depends_on", {}) != context:
            errors[key] = "Trường phụ thuộc đã thay đổi. Vui lòng chọn lại."
            continue
        try:
            current = await runtime.context.profile_schema_client.get_field_option_set(
                resource.key, key, None, context,
                odoo_user_id=int(state["trusted_context"]["odoo_user_id"]),
                request_id=state["request_id"],
            )
        except ProfileSchemaError:
            errors[key] = "Không thể kiểm tra danh sách hiện tại. Vui lòng chọn lại."
            continue
        if current.option_set_id != issued.get("option_set_id"):
            errors[key] = "Danh sách lựa chọn đã thay đổi. Vui lòng chọn lại."
    return errors


def _embedded_option_set_id(field, options):
    payload = json.dumps(
        {
            "field": field.key,
            "values": [str(item.get("value")) for item in options],
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _same_value(current: Any, proposed: Any) -> bool:
    """Compatibility helper for callers without field metadata."""
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
        direct_fields = [
            field for field in section.direct_fields
            if field.allows(
                Operation.UPDATE if operation is Operation.CREATE else operation
            )
        ]
        if resources or direct_fields:
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


async def _clarify_direct_value(
    state: ChatGraphState,
    runtime: Runtime[GraphContext],
    started: float,
    classification: QueryClassification,
    workflow_data: dict[str, Any],
    section: ProfileSection,
    field: ProfileField,
    field_keys: list[str],
    record_reference: str | None,
    changes: dict[str, Any],
    *,
    current_snapshot: dict[str, Any],
    missing_profile_slots: list[str],
    error_message: str | None = None,
) -> dict[str, object]:
    workflow_data = {
        **workflow_data,
        "profile_write_mode": field.write_mode.value,
        "operation": Operation.UPDATE.value,
    }
    options: list[dict[str, Any]] = []
    input_type = input_type_for_field(field)
    if input_type in {"single_select", "searchable_select"}:
        registry_options = await (
            runtime.context.profile_schema_client.get_section_field_options(
                section.key,
                field.key,
                odoo_user_id=int(state["trusted_context"]["odoo_user_id"]),
                request_id=state["request_id"],
            )
        )
        options = _options(registry_options)
    current_label = _display_value(current_snapshot.get(field.key))
    text = error_message or (
        f"{field.label} hiện tại là {current_label}. Bạn muốn đổi thành gì?"
        if current_label
        else f"Bạn muốn nhập {field.label} là gì?"
    )
    return await _clarification(
        state, runtime, started, classification, Operation.UPDATE,
        workflow_data, section_key=section.key, resource_key=None,
        field_keys=field_keys, record_reference=record_reference,
        changes=changes, slot_name=field.key, input_type=input_type,
        text=text,
        options=options, missing_profile_slots=missing_profile_slots,
    )


async def _derived_redirect(
    state: ChatGraphState,
    runtime: Runtime[GraphContext],
    started: float,
    classification: QueryClassification,
    workflow_data: dict[str, Any],
    *,
    section_key: str,
    field: ProfileField,
    changes: dict[str, Any],
) -> dict[str, object]:
    derived_resource = str(field.derived_from_resource)
    workflow_data = {
        **workflow_data,
        "derived_from_resource": derived_resource,
        "derived_field_key": field.key,
    }
    return await _clarification(
        state, runtime, started, classification, Operation.UPDATE,
        workflow_data, section_key=section_key, resource_key=None,
        field_keys=[field.key], record_reference=None, changes=changes,
        slot_name="derived_resource_action", input_type="single_select",
        text=(
            "Thông tin này được hệ thống tổng hợp từ quá trình "
            "đào tạo. Bạn muốn thao tác thế nào?"
        ),
        options=[
            {"value": "create", "label": "Thêm trình độ đào tạo",
             "description": None},
            {"value": "update", "label": "Sửa trình độ đã có",
             "description": None},
        ],
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
    error_message: str | None = None,
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
                context={
                    key: (
                        changes[key]
                        if key in changes
                        else workflow_data.get(
                            "profile_current_snapshot", {}
                        ).get(key, {}).get("value")
                        if isinstance(
                            workflow_data.get(
                                "profile_current_snapshot", {}
                            ).get(key), dict
                        )
                        else workflow_data.get(
                            "profile_current_snapshot", {}
                        ).get(key)
                    )
                    for key in field.options_context_keys
                    if key in changes
                    or key in workflow_data.get("profile_current_snapshot", {})
                },
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
        text=error_message or f"Bạn muốn nhập {field.label} là gì?",
        options=options,
        missing_profile_slots=missing_profile_slots,
        extra_metadata={
            "resource_key": resource.key,
            "field_key": field.key,
            "options_context": {
                key: changes.get(key)
                for key in field.options_context_keys
                if changes.get(key) is not None
            },
            "description": field.description,
        },
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
    extra_metadata: dict[str, Any] | None = None,
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
    if extra_metadata:
        clarification.update(extra_metadata)
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


def _merge_profile_target(
    section_key: str | None,
    resource_key: str | None,
    field_keys: list[str],
    record_reference: str | None,
    resolution: ProfileTargetResolution,
) -> tuple[str | None, str | None, list[str], str | None]:
    """Merge resolver output without replacing a useful target with empties."""
    return (
        resolution.section_key
        if resolution.section_key is not None
        else section_key,
        resolution.resource_key
        if resolution.resource_key is not None
        else resource_key,
        resolution.field_keys if resolution.field_keys else field_keys,
        resolution.record_reference_text
        if resolution.record_reference_text is not None
        else record_reference,
    )


def _options(items: Any) -> list[dict[str, Any]]:
    return [
        {
            "value": str(getattr(item, "value", getattr(item, "key", ""))),
            "label": str(getattr(item, "label", "")),
            "description": getattr(item, "description", None),
        }
        for item in items
    ]


def _section_item_options(
    section: ProfileSection,
    resources: list[ProfileResource],
    operation: Operation,
) -> list[dict[str, Any]]:
    direct_operation = (
        Operation.UPDATE if operation is Operation.CREATE else operation
    )
    options = _options(
        field for field in section.direct_fields
        if field.allows(direct_operation) or field.derived_from_resource
    )
    for resource in resources:
        resource_operation = (
            Operation.UPDATE
            if operation is Operation.CREATE
            and resource.resource_type == "singleton"
            else operation
        )
        if resource.section_key == section.key and resource.allows(resource_operation):
            options.extend(_options([resource]))
    return options


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
