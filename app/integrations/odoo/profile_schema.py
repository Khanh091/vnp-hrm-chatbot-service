from __future__ import annotations

import re
import json
from dataclasses import dataclass
from enum import Enum
from time import monotonic
from typing import Any, TypeVar

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from app.integrations.odoo.client import OdooClient
from app.integrations.odoo.exceptions import (
    OdooAccessDeniedError,
    OdooBusinessValidationError,
    OdooRecordNotFoundError,
)
from app.routing.taxonomy import Operation


class ProfileWriteMode(str, Enum):
    DIRECT = "direct"
    APPROVAL_REQUEST = "approval_request"
    FORBIDDEN = "forbidden"


class ProfileSchemaError(RuntimeError):
    def __init__(self, reason_code: str, message: str) -> None:
        super().__init__(message)
        self.reason_code = reason_code


class ProfileSchemaKeyNotFoundError(ProfileSchemaError):
    def __init__(self, message: str = "Unknown profile schema key") -> None:
        super().__init__("PROFILE_SCHEMA_KEY_NOT_FOUND", message)


class ProfileSchemaAccessDeniedError(ProfileSchemaError):
    def __init__(self) -> None:
        super().__init__(
            "PROFILE_SCHEMA_ACCESS_DENIED",
            "Actor cannot access this profile schema entry",
        )


class ProfileSchemaContractError(ProfileSchemaError):
    def __init__(self, message: str) -> None:
        super().__init__("PROFILE_SCHEMA_CONTRACT_ERROR", message)


class ProfileOption(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    value: JsonValue
    label: str
    description: str | None = None


class ProfileField(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    key: str
    label: str
    field_type: str
    readable: bool
    creatable: bool
    updatable: bool
    deletable: bool
    required_on_create: bool = False
    sensitive: bool = False
    write_mode: ProfileWriteMode = ProfileWriteMode.FORBIDDEN
    aliases: tuple[str, ...] = ()
    selection_values: tuple[ProfileOption, ...] = ()
    option_provider: str | None = None
    description: str | None = None
    section_key: str | None = None
    resource_key: str | None = None
    derived_from_resource: str | None = None
    restriction_reason: str | None = None
    depends_on: tuple[str, ...] = ()
    options_context_keys: tuple[str, ...] = ()
    clear_when_dependency_changes: bool = False
    default_value: JsonValue | None = None
    validator: str | None = None
    range_group: str | None = None
    unsupported_input_type: str | None = None

    def allows(self, operation: Operation) -> bool:
        return {
            Operation.CREATE: self.creatable,
            Operation.UPDATE: self.updatable,
            Operation.DELETE: self.deletable,
            Operation.READ: self.readable,
        }.get(operation, False)


class ProfileResource(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    key: str
    label: str
    section_key: str
    resource_type: str
    readable: bool
    creatable: bool
    updatable: bool
    deletable: bool
    aliases: tuple[str, ...] = ()
    read_capability: str | None = None
    create_capability: str | None = None
    update_capability: str | None = None
    delete_capability: str | None = None
    record_label_field: str | None = None
    sort_fields: tuple[str, ...] = ()
    disambiguation_fields: tuple[str, ...] = ()
    deletion_mode: str | None = None
    fields: tuple[ProfileField, ...] = ()

    def allows(self, operation: Operation) -> bool:
        return {
            Operation.CREATE: self.creatable,
            Operation.UPDATE: self.updatable,
            Operation.DELETE: self.deletable,
            Operation.READ: self.readable,
        }.get(operation, False)


class ProfileSection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    key: str
    label: str
    aliases: tuple[str, ...] = ()
    direct_fields: tuple[ProfileField, ...] = ()
    fields: tuple[ProfileField, ...] = ()
    resource_keys: tuple[str, ...] = ()
    resources: tuple[ProfileResource, ...] = ()


class ProfileSectionList(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    items: tuple[ProfileSection, ...] = ()


class ProfileResourceList(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    items: tuple[ProfileResource, ...] = ()


class ProfileFieldList(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    resource_key: str
    items: tuple[ProfileField, ...] = ()


class ProfileOptionList(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    section_key: str | None = None
    resource_key: str | None = None
    field_key: str
    option_set_id: str | None = None
    depends_on: dict[str, JsonValue] = Field(default_factory=dict)
    items: tuple[ProfileOption, ...] = ()


class ProfileRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    record_id: int
    label: str
    description: str | None = None
    snapshot: dict[str, Any]
    version: str
    can_update: bool
    can_delete: bool


class ProfileRecordList(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    resource_key: str
    items: tuple[ProfileRecord, ...] = ()


class ProfileSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    section_key: str | None = None
    resource_key: str | None = None
    snapshot: dict[str, Any]
    version: str
    approved_snapshot: dict[str, Any] | None = None
    edition_snapshot: dict[str, Any] | None = None


class ProfileExecutionResult(BaseModel):
    model_config = ConfigDict(extra="allow", frozen=True)
    section_key: str | None = None
    resource_key: str | None = None
    operation: str
    write_mode: str
    request_id: int | None = None
    state: str | None = None
    message: str | None = None
    draft_saved: bool | None = None
    snapshot: dict[str, Any] | None = None
    version: str | None = None
    record_id: int | None = None


class ProfileDirectResult(BaseModel):
    model_config = ConfigDict(extra="allow", frozen=True)


SchemaT = TypeVar("SchemaT", bound=BaseModel)
_CANONICAL_KEY = re.compile(r"^[a-z][a-z0-9_]*$")


@dataclass(frozen=True)
class _CacheEntry:
    expires_at: float
    value: BaseModel


class ProfileSchemaClient:
    """Actor-scoped access to the public Profile CRUD Schema Registry."""

    SECTIONS_PATH = "/api/hrm-chatbot/v1/profile/schema/sections"

    def __init__(
        self,
        odoo_client: OdooClient,
        *,
        cache_ttl_seconds: float = 30,
    ) -> None:
        self._odoo = odoo_client
        self._ttl = max(cache_ttl_seconds, 0)
        self._cache: dict[tuple[Any, ...], _CacheEntry] = {}

    async def get_sections(
        self,
        operation: Operation | None,
        *,
        odoo_user_id: int,
        request_id: str,
    ) -> tuple[ProfileSection, ...]:
        result = await self._get(
            self.SECTIONS_PATH,
            ProfileSectionList,
            actor=odoo_user_id,
            request_id=request_id,
            operation=operation,
        )
        return result.items

    async def get_resources(
        self,
        section_key: str,
        operation: Operation | None,
        *,
        odoo_user_id: int,
        request_id: str,
    ) -> tuple[ProfileResource, ...]:
        self._validate_key(section_key)
        result = await self._get(
            f"{self.SECTIONS_PATH}/{section_key}/resources",
            ProfileResourceList,
            actor=odoo_user_id,
            request_id=request_id,
            operation=operation,
        )
        return result.items

    async def get_section(
        self,
        section_key: str,
        operation: Operation | None,
        *,
        odoo_user_id: int,
        request_id: str,
    ) -> ProfileSection:
        self._validate_key(section_key)
        return await self._get(
            f"{self.SECTIONS_PATH}/{section_key}",
            ProfileSection,
            actor=odoo_user_id,
            request_id=request_id,
            operation=operation,
        )

    async def get_section_fields(
        self,
        section_key: str,
        operation: Operation | None,
        *,
        odoo_user_id: int,
        request_id: str,
    ) -> tuple[ProfileField, ...]:
        section = await self.get_section(
            section_key,
            operation,
            odoo_user_id=odoo_user_id,
            request_id=request_id,
        )
        return section.direct_fields

    async def get_resource(
        self,
        resource_key: str,
        *,
        odoo_user_id: int,
        request_id: str,
    ) -> ProfileResource:
        self._validate_key(resource_key)
        return await self._get(
            f"{self.SECTIONS_PATH.rsplit('/sections', 1)[0]}/resources/{resource_key}",
            ProfileResource,
            actor=odoo_user_id,
            request_id=request_id,
        )

    async def get_fields(
        self,
        resource_key: str,
        operation: Operation | None,
        *,
        odoo_user_id: int,
        request_id: str,
    ) -> tuple[ProfileField, ...]:
        self._validate_key(resource_key)
        result = await self._get(
            f"{self.SECTIONS_PATH.rsplit('/sections', 1)[0]}/resources/"
            f"{resource_key}/fields",
            ProfileFieldList,
            actor=odoo_user_id,
            request_id=request_id,
            operation=operation,
        )
        return result.items

    async def get_field_options(
        self,
        resource_key: str,
        field_key: str,
        query: str | None = None,
        context: dict[str, JsonValue] | None = None,
        *,
        odoo_user_id: int,
        request_id: str,
    ) -> tuple[ProfileOption, ...]:
        result = await self.get_field_option_set(
            resource_key, field_key, query, context,
            odoo_user_id=odoo_user_id, request_id=request_id,
        )
        return result.items

    async def get_field_option_set(
        self,
        resource_key: str,
        field_key: str,
        query: str | None = None,
        context: dict[str, JsonValue] | None = None,
        *,
        odoo_user_id: int,
        request_id: str,
    ) -> ProfileOptionList:
        self._validate_key(resource_key)
        self._validate_key(field_key)
        return await self._get(
            f"{self.SECTIONS_PATH.rsplit('/sections', 1)[0]}/resources/"
            f"{resource_key}/fields/{field_key}/options",
            ProfileOptionList,
            actor=odoo_user_id,
            request_id=request_id,
            query=query,
            option_context=context,
        )

    async def get_section_field_options(
        self,
        section_key: str,
        field_key: str,
        query: str | None = None,
        *,
        odoo_user_id: int,
        request_id: str,
    ) -> tuple[ProfileOption, ...]:
        self._validate_key(section_key)
        self._validate_key(field_key)
        result = await self._get(
            f"{self.SECTIONS_PATH}/{section_key}/fields/{field_key}/options",
            ProfileOptionList,
            actor=odoo_user_id,
            request_id=request_id,
            query=query,
        )
        return result.items

    async def list_records(self, resource_key: str, *, odoo_user_id: int,
                           request_id: str) -> tuple[ProfileRecord, ...]:
        self._validate_key(resource_key)
        result = await self._profile_request(
            "GET", f"/api/hrm-chatbot/v1/profile/resources/{resource_key}",
            ProfileRecordList, odoo_user_id=odoo_user_id, request_id=request_id,
        )
        return result.items

    async def get_record(self, resource_key: str, record_id: int, *,
                         odoo_user_id: int, request_id: str) -> ProfileRecord:
        self._validate_key(resource_key)
        if record_id <= 0:
            raise ProfileSchemaKeyNotFoundError("Invalid profile record")
        return await self._profile_request(
            "GET", f"/api/hrm-chatbot/v1/profile/resources/{resource_key}/{record_id}",
            ProfileRecord, odoo_user_id=odoo_user_id, request_id=request_id,
        )

    async def get_current_snapshot(self, resource_key: str, *, odoo_user_id: int,
                                   request_id: str) -> ProfileSnapshot:
        self._validate_key(resource_key)
        return await self._profile_request(
            "GET", f"/api/hrm-chatbot/v1/profile/resources/{resource_key}/current",
            ProfileSnapshot, odoo_user_id=odoo_user_id, request_id=request_id,
        )

    async def get_section_snapshot(self, section_key: str, *, odoo_user_id: int,
                                   request_id: str) -> ProfileSnapshot:
        self._validate_key(section_key)
        return await self._profile_request(
            "GET", f"/api/hrm-chatbot/v1/profile/sections/{section_key}/current",
            ProfileSnapshot, odoo_user_id=odoo_user_id, request_id=request_id,
        )

    async def execute_change_request(
        self,
        payload: dict[str, Any],
        *,
        odoo_user_id: int,
        request_id: str,
    ) -> ProfileExecutionResult:
        resource_key = payload.get("resource_key")
        section_key = payload.get("section_key")
        if bool(resource_key) == bool(section_key):
            raise ProfileSchemaContractError(
                "Profile write requires exactly one section or resource"
            )
        if resource_key:
            self._validate_key(str(resource_key))
        if section_key:
            self._validate_key(str(section_key))
        body = {
            "odoo_user_id": odoo_user_id,
            "resource_key": resource_key,
            "section_key": section_key,
            "operation": payload.get("operation"),
            "changes": payload.get("changes", {}),
            "record_id": payload.get("record_id"),
            "expected_version": payload.get("expected_version"),
            "idempotency_key": payload.get("idempotency_key"),
        }
        body = {key: value for key, value in body.items() if value is not None}
        return await self._profile_request(
            "POST", "/api/hrm-chatbot/v1/profile/change-requests",
            ProfileExecutionResult, odoo_user_id=odoo_user_id,
            request_id=request_id, payload=body,
        )

    async def save_draft(
        self,
        payload: dict[str, Any],
        *,
        odoo_user_id: int,
        request_id: str,
    ) -> ProfileExecutionResult:
        resource_key = payload.get("resource_key")
        section_key = payload.get("section_key")
        if bool(resource_key) == bool(section_key):
            raise ProfileSchemaContractError(
                "Profile draft requires exactly one section or resource"
            )
        if resource_key:
            self._validate_key(str(resource_key))
        if section_key:
            self._validate_key(str(section_key))
        body = {
            "odoo_user_id": odoo_user_id,
            "resource_key": resource_key,
            "section_key": section_key,
            "operation": payload.get("operation"),
            "changes": payload.get("changes", {}),
            "record_id": payload.get("record_id"),
            "expected_version": payload.get("expected_version"),
            "idempotency_key": payload.get("idempotency_key"),
        }
        body = {key: value for key, value in body.items()
                if value is not None}
        return await self._profile_request(
            "POST", "/api/hrm-chatbot/v1/profile/drafts",
            ProfileExecutionResult, odoo_user_id=odoo_user_id,
            request_id=request_id, payload=body,
        )

    async def execute_direct(self, payload: dict[str, Any], *, odoo_user_id: int,
                             request_id: str) -> dict[str, Any]:
        resource_key = str(payload.get("resource_key", ""))
        self._validate_key(resource_key)
        operation = str(payload.get("operation", ""))
        record_id = payload.get("record_id")
        methods = {"create": "POST", "update": "PATCH", "delete": "DELETE"}
        method = methods.get(operation)
        if method is None or (operation in {"update", "delete"} and not record_id):
            raise ProfileSchemaContractError("Invalid direct profile operation")
        path = f"/api/hrm-chatbot/v1/profile/resources/{resource_key}"
        if record_id:
            path += f"/{int(record_id)}"
        body = {
            "odoo_user_id": odoo_user_id,
            "changes": payload.get("changes", {}),
            "expected_version": payload.get("expected_version"),
            "idempotency_key": payload.get("idempotency_key"),
        }
        body = {key: value for key, value in body.items() if value is not None}
        result = await self._profile_request(
            method, path, ProfileDirectResult, odoo_user_id=odoo_user_id,
            request_id=request_id, payload=body,
        )
        return result.model_dump(mode="json")

    async def _profile_request(self, method: str, path: str, model: type[SchemaT], *,
                               odoo_user_id: int, request_id: str,
                               payload: dict[str, Any] | None = None) -> SchemaT:
        if odoo_user_id <= 0:
            raise ProfileSchemaAccessDeniedError()
        values = payload or {"odoo_user_id": odoo_user_id}
        try:
            return await self._odoo.request_profile_resource(
                method,
                path,
                request_id=request_id,
                response_model=model,
                payload=values,
            )
        except OdooAccessDeniedError as error:
            if str(error.odoo_error_code or "").startswith("PROFILE_"):
                raise ProfileSchemaError(
                    str(error.odoo_error_code), str(error)
                ) from error
            raise ProfileSchemaAccessDeniedError() from error
        except OdooRecordNotFoundError as error:
            if str(error.odoo_error_code or "").startswith("PROFILE_"):
                raise ProfileSchemaError(
                    str(error.odoo_error_code), str(error)
                ) from error
            raise ProfileSchemaKeyNotFoundError(str(error)) from error
        except OdooBusinessValidationError as error:
            raise ProfileSchemaError(error.odoo_error_code, str(error)) from error

    async def _get(
        self,
        path: str,
        model: type[SchemaT],
        *,
        actor: int,
        request_id: str,
        operation: Operation | None = None,
        query: str | None = None,
        option_context: dict[str, JsonValue] | None = None,
    ) -> SchemaT:
        if actor <= 0:
            raise ProfileSchemaAccessDeniedError()
        if operation in {Operation.CANCEL, Operation.NONE}:
            raise ProfileSchemaContractError("Unsupported profile operation")
        params: dict[str, Any] = {"odoo_user_id": actor}
        if operation is not None:
            params["operation"] = operation.value
        if query:
            params["query"] = query[:100]
        if option_context:
            if any(not _CANONICAL_KEY.fullmatch(key)
                   for key in option_context):
                raise ProfileSchemaContractError("Invalid option context")
            params["context"] = json.dumps(
                option_context, ensure_ascii=False, sort_keys=True
            )
        context_key = json.dumps(option_context or {}, sort_keys=True)
        cache_key = (actor, path, operation.value if operation else None,
                     query, context_key)
        cached = self._cache.get(cache_key)
        if cached and cached.expires_at > monotonic():
            return cached.value  # type: ignore[return-value]
        try:
            result = await self._odoo.request_profile_schema(
                path,
                request_id=request_id,
                response_model=model,
                params=params,
            )
        except OdooAccessDeniedError as error:
            raise ProfileSchemaAccessDeniedError() from error
        except OdooRecordNotFoundError as error:
            raise ProfileSchemaKeyNotFoundError() from error
        except OdooBusinessValidationError as error:
            if error.odoo_error_code in {"INVALID_REQUEST", "RECORD_NOT_FOUND"}:
                raise ProfileSchemaKeyNotFoundError(str(error)) from error
            raise
        if self._ttl:
            self._cache[cache_key] = _CacheEntry(monotonic() + self._ttl, result)
        return result

    @staticmethod
    def _validate_key(key: str) -> None:
        if not _CANONICAL_KEY.fullmatch(key):
            raise ProfileSchemaKeyNotFoundError()


def input_type_for_field(field: ProfileField) -> str:
    if field.unsupported_input_type:
        return field.unsupported_input_type
    if field.option_provider:
        return "searchable_select"
    if field.selection_values:
        return "single_select"
    return {
        "selection": "single_select",
        "many2one": "searchable_select",
        "boolean": "boolean",
        "date": "date",
        "integer": "number",
        "decimal": "number",
        "float": "number",
        "binary": "attachment",
        "attachment": "attachment",
    }.get(field.field_type, "text")


__all__ = [
    "ProfileField",
    "ProfileOption",
    "ProfileResource",
    "ProfileSchemaAccessDeniedError",
    "ProfileSchemaClient",
    "ProfileSchemaContractError",
    "ProfileSchemaError",
    "ProfileSchemaKeyNotFoundError",
    "ProfileSection",
    "ProfileWriteMode",
    "input_type_for_field",
]
