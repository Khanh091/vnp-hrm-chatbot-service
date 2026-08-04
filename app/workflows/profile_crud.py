from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict

from app.integrations.odoo.profile_schema import (
    ProfileField,
    ProfileOption,
    ProfileResource,
    ProfileSchemaClient,
    ProfileWriteMode,
    input_type_for_field,
)
from app.routing.profile_target_resolver import (
    ProfileTargetOutsideAllowlistError,
    ProfileTargetResolver,
)
from app.routing.taxonomy import Intent, Operation


class ProfileWorkflowResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    state: dict[str, Any]
    text: str
    clarification: dict[str, Any] | None = None
    error_code: str | None = None


class ProfileCrudWorkflow:
    def __init__(
        self,
        schema: ProfileSchemaClient,
        resolver: ProfileTargetResolver,
    ) -> None:
        self._schema = schema
        self._resolver = resolver

    async def start(
        self,
        *,
        query: str,
        intent: Intent,
        operation: Operation,
        actor: int,
        request_id: str,
    ) -> ProfileWorkflowResult:
        sections = await self._schema.get_sections(
            operation, odoo_user_id=actor, request_id=request_id
        )
        resource_summaries = tuple(
            resource
            for section in sections
            for resource in await self._schema.get_resources(
                section.key,
                operation,
                odoo_user_id=actor,
                request_id=request_id,
            )
        )
        resources = tuple(
            [
                await self._schema.get_resource(
                    item.key, odoo_user_id=actor, request_id=request_id
                )
                for item in resource_summaries
            ]
        )
        base = self.empty_state(operation)
        try:
            target = await self._resolver.resolve(
                original_query=query,
                intent=intent,
                operation=operation,
                sections=sections,
                resources=resources,
                request_id=request_id,
            )
        except ProfileTargetOutsideAllowlistError:
            return self._clarify(
                base,
                "Bạn muốn thao tác nhóm thông tin nào?",
                "section_select",
                "profile_section_key",
                [self._option(item) for item in sections],
                error_code="PROFILE_TARGET_OUTSIDE_ALLOWLIST",
            )
        state = {
            **base,
            "profile_section_key": target.section_key,
            "profile_resource_key": target.resource_key,
            "profile_field_keys": target.field_keys,
            "profile_record_reference": target.record_reference_text,
        }
        if not target.section_key:
            return self._clarify(
                state, "Bạn muốn thao tác nhóm thông tin nào?", "section_select",
                "profile_section_key", [self._option(item) for item in sections]
            )
        relevant = tuple(
            item for item in resources if item.section_key == target.section_key
        )
        if not target.resource_key:
            return self._clarify(
                state, "Bạn muốn sửa nhóm thông tin nào?", "resource_select",
                "profile_resource_key", [self._option(item) for item in relevant]
            )
        resource = next(item for item in resources if item.key == target.resource_key)
        return await self._after_resource(
            state, resource, operation, actor=actor, request_id=request_id
        )

    async def advance(
        self,
        state: dict[str, Any],
        *,
        slot: str,
        value: Any,
        actor: int,
        request_id: str,
    ) -> ProfileWorkflowResult:
        operation = Operation(state["profile_operation"])
        updated = dict(state)
        if slot == "profile_section_key":
            updated[slot] = str(value)
            resources = await self._schema.get_resources(
                str(value), operation, odoo_user_id=actor, request_id=request_id
            )
            return self._clarify(
                updated, "Bạn muốn thao tác nhóm thông tin nào?", "resource_select",
                "profile_resource_key", [self._option(item) for item in resources]
            )
        if slot == "profile_resource_key":
            updated[slot] = str(value)
            resource = await self._schema.get_resource(
                str(value), odoo_user_id=actor, request_id=request_id
            )
            return await self._after_resource(
                updated, resource, operation, actor=actor, request_id=request_id
            )
        resource = await self._schema.get_resource(
            str(updated["profile_resource_key"]),
            odoo_user_id=actor,
            request_id=request_id,
        )
        if slot == "profile_field_keys":
            field = next((item for item in resource.fields if item.key == value), None)
            if field is None or not field.allows(operation):
                return self._forbidden(updated, field)
            updated[slot] = [field.key]
            updated["missing_profile_slots"] = [field.key]
            updated["profile_write_mode"] = field.write_mode
            return await self._ask_value(
                updated, resource, field, actor=actor, request_id=request_id
            )
        if slot == "profile_record_id":
            updated[slot] = int(value)
            if operation is Operation.UPDATE and not updated["profile_field_keys"]:
                fields = [item for item in resource.fields if item.allows(operation)]
                return self._clarify(
                    updated, "Bạn muốn sửa thông tin nào?", "field_select",
                    "profile_field_keys", [self._option(item) for item in fields]
                )
        else:
            updated["profile_changes"] = {
                **updated.get("profile_changes", {}), slot: value
            }
            missing = [
                item for item in updated.get("missing_profile_slots", []) if item != slot
            ]
            updated["missing_profile_slots"] = missing
            if missing:
                field = next(item for item in resource.fields if item.key == missing[0])
                return await self._ask_value(
                    updated, resource, field, actor=actor, request_id=request_id
                )
        return self._not_implemented(updated)

    async def _after_resource(
        self,
        state: dict[str, Any],
        resource: ProfileResource,
        operation: Operation,
        *,
        actor: int,
        request_id: str,
    ) -> ProfileWorkflowResult:
        if not resource.allows(operation):
            return self._forbidden(state, None)
        chosen = [item for item in resource.fields if item.key in state["profile_field_keys"]]
        forbidden = next((item for item in chosen if not item.allows(operation)), None)
        if forbidden:
            return self._forbidden(state, forbidden)
        if operation is Operation.CREATE:
            required = [item for item in resource.fields if item.required_on_create]
            state["missing_profile_slots"] = [item.key for item in required]
            state["profile_write_mode"] = self._write_mode(required)
            if required:
                return await self._ask_value(
                    state, resource, required[0], actor=actor, request_id=request_id
                )
        if operation is Operation.UPDATE and resource.resource_type == "collection" \
                and state["profile_record_id"] is None:
            # record_reference is kept as text; a future read capability supplies IDs.
            return self._clarify(
                state, "Bạn muốn chọn dòng hồ sơ nào?", "record_select",
                "profile_record_id", []
            )
        if operation is Operation.DELETE and resource.resource_type == "collection":
            return self._clarify(
                state, "Bạn muốn chọn dòng hồ sơ nào?", "record_select",
                "profile_record_id", []
            )
        if operation is Operation.UPDATE and not chosen:
            fields = [item for item in resource.fields if item.allows(operation)]
            return self._clarify(
                state, "Bạn muốn sửa thông tin nào?", "field_select",
                "profile_field_keys", [self._option(item) for item in fields]
            )
        if operation is Operation.UPDATE and chosen:
            state["missing_profile_slots"] = [item.key for item in chosen]
            state["profile_write_mode"] = self._write_mode(chosen)
            return await self._ask_value(
                state, resource, chosen[0], actor=actor, request_id=request_id
            )
        return self._not_implemented(state)

    async def _ask_value(
        self,
        state: dict[str, Any],
        resource: ProfileResource,
        field: ProfileField,
        *,
        actor: int,
        request_id: str,
    ) -> ProfileWorkflowResult:
        input_type = input_type_for_field(field)
        options = None
        if input_type in {"single_select", "searchable_select"}:
            values = await self._schema.get_field_options(
                resource.key,
                field.key,
                odoo_user_id=actor,
                request_id=request_id,
            )
            options = [self._option(item) for item in values]
        return self._clarify(
            state, f"Bạn muốn nhập {field.label} là gì?", input_type,
            field.key, options
        )

    @staticmethod
    def empty_state(operation: Operation) -> dict[str, Any]:
        return {
            "profile_section_key": None, "profile_resource_key": None,
            "profile_field_keys": [], "profile_record_reference": None,
            "profile_record_id": None, "profile_write_mode": None,
            "profile_current_snapshot": None, "profile_changes": {},
            "missing_profile_slots": [], "profile_operation": operation.value,
        }

    @staticmethod
    def _write_mode(fields: list[ProfileField]) -> str:
        modes = {item.write_mode for item in fields}
        if ProfileWriteMode.FORBIDDEN in modes:
            return ProfileWriteMode.FORBIDDEN
        if ProfileWriteMode.APPROVAL_REQUEST in modes:
            return ProfileWriteMode.APPROVAL_REQUEST
        return ProfileWriteMode.DIRECT

    @staticmethod
    def _option(item: Any) -> dict[str, Any]:
        return {
            "value": str(getattr(item, "key", getattr(item, "value", ""))),
            "label": item.label,
            "description": getattr(item, "description", None),
        }

    @staticmethod
    def _clarify(
        state: dict[str, Any], text: str, input_type: str, slot: str,
        options: list[dict[str, Any]] | None, error_code: str | None = None,
    ) -> ProfileWorkflowResult:
        clarification: dict[str, Any] = {"input_type": input_type, "slot_name": slot}
        if options is not None:
            clarification["options"] = options
        return ProfileWorkflowResult(
            state=state, text=text, clarification=clarification, error_code=error_code
        )

    @staticmethod
    def _forbidden(
        state: dict[str, Any], field: ProfileField | None
    ) -> ProfileWorkflowResult:
        text = "Thông tin này không thể thay đổi qua hồ sơ tự khai."
        if field and field.description:
            text += f" {field.description}"
        return ProfileWorkflowResult(
            state=state, text=text, error_code="PROFILE_OPERATION_FORBIDDEN"
        )

    @staticmethod
    def _not_implemented(state: dict[str, Any]) -> ProfileWorkflowResult:
        return ProfileWorkflowResult(
            state=state,
            text="Chức năng ghi hồ sơ đang được hoàn thiện.",
            error_code="PROFILE_WRITE_EXECUTION_NOT_IMPLEMENTED",
        )
