from __future__ import annotations

import asyncio
import unicodedata
from time import perf_counter
from typing import Any

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
    edit_action = (
        str(collected.get("profile_edit_action"))
        if answer_field == "profile_edit_action"
        and collected.get("profile_edit_action") is not None
        else None
    )
    workflow_data["profile_edit_action"] = edit_action

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

        # Follow-up answers are stored by canonical slot name. Merge every field
        # emitted by this bounded resource, not only the initially resolved keys.
        # Collection creates often start without field_keys, which previously made
        # a value such as "IELTS" disappear and caused the same question to repeat.
        previous_changes = dict(changes)
        for definition in resource.fields:
            if definition.key in collected:
                changes[definition.key] = collected[definition.key]
                previous_value = previous_changes.get(
                    definition.key,
                    workflow_data.get("profile_current_snapshot", {}).get(
                        definition.key
                    ),
                )
                if not _same_value(previous_value, collected[definition.key]):
                    for dependent in resource.fields:
                        if (
                            definition.key in dependent.depends_on
                            and dependent.clear_when_dependency_changes
                        ):
                            changes.pop(dependent.key, None)

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
            changes = {
                key: value for key, value in changes.items()
                if not _same_value(current_snapshot.get(key), value)
            }
            if not changes:
                return await _profile_draft_form(
                    state, runtime, started, classification, operation,
                    workflow_data, resource, list(operation_fields),
                    record_reference, {}, current_snapshot,
                    expected_version,
                    notice="Giá trị bạn chọn không thay đổi; bản nháp chưa có cập nhật mới.",
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
    for field in section.direct_fields:
        if field.key in collected:
            changes[field.key] = collected[field.key]

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
    structured_answer = state.get("clarification")
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

    changes = {
        key: value for key, value in changes.items()
        if not _same_value(current_snapshot.get(key), value)
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
) -> list[dict[str, Any]]:
    rows = []
    for field in fields:
        current = current_snapshot.get(field.key)
        changed = field.key in changes and not _same_value(
            current, changes[field.key]
        )
        rows.append({
            "label": field.label,
            "current_value": _display_value(current),
            "draft_value": (
                _display_value(changes[field.key]) if field.key in changes
                else None
            ),
            "status": "changed" if changed else "unchanged",
            "input_type": input_type_for_field(field),
            "description": field.description,
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
) -> dict[str, object]:
    editable = [field for field in fields if field.allows(operation)]
    options = [
        {"value": f"edit:{field.key}", "label": f"Sửa {field.label}",
         "description": field.description}
        for field in editable
    ]
    if changes:
        options.append({"value": "finish", "label": "Hoàn tất",
                        "description": None})
    options.append({"value": "cancel", "label": "Hủy",
                    "description": None})
    workflow_data.update({
        "profile_current_snapshot": current_snapshot,
        "profile_expected_version": expected_version,
        "profile_changes": changes,
        "profile_edit_status": "EDITING",
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
                list(resource.fields), current_snapshot, changes
            ),
            "status": "EDITING",
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
) -> dict[str, object]:
    options = []
    if changes:
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
            "fields": _draft_field_rows(fields, current_snapshot, changes),
            "status": "EDITING",
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
) -> dict[str, object]:
    workflow_data.update({
        "profile_current_snapshot": current_snapshot,
        "profile_expected_version": expected_version,
        "profile_changes": changes,
        "profile_record_id": record_id,
        "profile_edit_status": "REVIEWING",
    })
    return await _clarification(
        state, runtime, started, classification, operation, workflow_data,
        section_key=(section.key if section else resource.section_key),
        resource_key=(resource.key if resource else None),
        field_keys=[field.key for field in fields if field.key in changes],
        record_reference=None, changes=changes,
        slot_name="profile_edit_action", input_type="edit_session_actions",
        text="Hãy chọn lưu nháp hoặc gửi xác nhận.",
        options=[
            {"value": "save_draft", "label": "Lưu nháp", "description": None},
            {"value": "submit", "label": "Gửi xác nhận", "description": None},
            {"value": "continue", "label": "Tiếp tục chỉnh sửa", "description": None},
            {"value": "cancel", "label": "Hủy thay đổi", "description": None},
        ],
        extra_metadata={
            "title": resource.label if resource else section.label,
            "fields": _draft_field_rows(fields, current_snapshot, changes),
            "status": "REVIEWING",
            "write_mode": write_mode.value,
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
    payload = {
        "section_key": section.key if section else None,
        "resource_key": resource.key if resource else None,
        "operation": operation.value,
        "record_id": record_id,
        "changes": changes,
        "expected_version": expected_version,
        "idempotency_key": f"draft:{state['conversation_id']}:{state['request_id']}",
    }
    payload = {key: value for key, value in payload.items()
               if value is not None}
    result = await runtime.context.profile_schema_client.save_draft(
        payload,
        odoo_user_id=int(state["trusted_context"]["odoo_user_id"]),
        request_id=state["request_id"],
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
        if resource is None:
            raise ProfileTargetOutsideAllowlistError()
        fields_by_key = {field.key: field for field in resource.fields}
        summary = [
            {"label": fields_by_key[key].label, "old_value": None,
             "new_value": _display_value(value)}
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
