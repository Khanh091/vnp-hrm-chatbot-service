from __future__ import annotations

import re
from dataclasses import dataclass
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


class ProfileWriteMode(str):
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
    write_mode: str = ProfileWriteMode.FORBIDDEN
    aliases: tuple[str, ...] = ()
    selection_values: tuple[ProfileOption, ...] = ()
    option_provider: str | None = None
    description: str | None = None

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
    resource_keys: tuple[str, ...] = ()


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
    resource_key: str
    field_key: str
    items: tuple[ProfileOption, ...] = ()


SchemaT = TypeVar("SchemaT", bound=BaseModel)
_CANONICAL_KEY = re.compile(r"^[a-z][a-z0-9_]*$")


@dataclass(frozen=True)
class _CacheEntry:
    expires_at: float
    value: BaseModel


class ProfileSchemaClient:
    """Actor-scoped access to the public Profile CRUD Schema Registry."""

    SECTIONS_PATH = "/api/hrm-chatbot/v1/profile/schema/sections"

    def __init__(self, odoo_client: OdooClient, *, cache_ttl_seconds: float = 30) -> None:
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
            f"{self.SECTIONS_PATH.rsplit('/sections', 1)[0]}/resources/{resource_key}/fields",
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
        *,
        odoo_user_id: int,
        request_id: str,
    ) -> tuple[ProfileOption, ...]:
        self._validate_key(resource_key)
        self._validate_key(field_key)
        result = await self._get(
            f"{self.SECTIONS_PATH.rsplit('/sections', 1)[0]}/resources/"
            f"{resource_key}/fields/{field_key}/options",
            ProfileOptionList,
            actor=odoo_user_id,
            request_id=request_id,
            query=query,
        )
        return result.items

    async def _get(
        self,
        path: str,
        model: type[SchemaT],
        *,
        actor: int,
        request_id: str,
        operation: Operation | None = None,
        query: str | None = None,
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
        cache_key = (actor, path, operation.value if operation else None, query)
        cached = self._cache.get(cache_key)
        if cached and cached.expires_at > monotonic():
            return cached.value  # type: ignore[return-value]
        try:
            result = await self._odoo._request(
                "GET",
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
    return {
        "selection": "single_select",
        "many2one": "searchable_select",
        "boolean": "boolean",
        "date": "date",
        "integer": "number",
        "decimal": "number",
        "float": "number",
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
