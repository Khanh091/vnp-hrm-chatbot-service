from __future__ import annotations

from enum import Enum
from typing import Protocol, cast
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from app.context.actor import ActorContext
from app.context.entities import ResolvedSubject, SubjectMention
from app.integrations.odoo.client import OdooClient
from app.integrations.odoo.exceptions import (
    OdooAccessDeniedError,
    OdooError,
    OdooRecordNotFoundError,
)
from app.routing.taxonomy import SubjectType
from app.tools.definitions import ToolResponse


class SubjectLookupOption(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    value: int
    label: str
    employee_code: str | None = None


class SubjectResolutionStatus(str, Enum):
    RESOLVED = "resolved"
    NOT_FOUND = "not_found"
    AMBIGUOUS = "ambiguous"
    LOOKUP_UNAVAILABLE = "lookup_unavailable"


class SubjectResolution(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    status: SubjectResolutionStatus
    subject: ResolvedSubject | None = None
    options: list[SubjectLookupOption] = Field(default_factory=list)
    reason_code: str


class SubjectLookupProvider(Protocol):
    async def search_employees(
        self,
        *,
        name: str | None,
        code: str | None,
        actor: ActorContext,
    ) -> list[ResolvedSubject]: ...

    async def search_departments(
        self,
        *,
        name: str,
        actor: ActorContext,
    ) -> list[ResolvedSubject]: ...


class SubjectLookupError(RuntimeError):
    def __init__(self, reason_code: str) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code


class OdooSubjectLookupProvider:
    """Use only the explicit directory endpoints exposed by the Odoo module."""

    def __init__(self, client: OdooClient) -> None:
        self._client = client

    async def search_employees(
        self,
        *,
        name: str | None,
        code: str | None,
        actor: ActorContext,
    ) -> list[ResolvedSubject]:
        data = await self._request(
            method="POST",
            path="/api/v1/hrm/employees/search",
            actor=actor,
            payload={
                "name": name,
                "employee_code": code,
                "limit": 10,
            },
        )
        return [
            ResolvedSubject(
                type=SubjectType.EMPLOYEE,
                employee_id=item.get("employee_id"),
                employee_code=item.get("employee_code"),
                employee_name=item.get("full_name"),
                department_id=self._relation_id(item.get("department")),
                department_name=self._relation_name(item.get("department")),
                source="odoo_lookup",
            )
            for item in self._items(data)
            if isinstance(item.get("employee_id"), int)
        ]

    async def search_departments(
        self,
        *,
        name: str,
        actor: ActorContext,
    ) -> list[ResolvedSubject]:
        data = await self._request(
            method="POST",
            path="/api/v1/hrm/departments/search",
            actor=actor,
            payload={"name": name, "limit": 10},
        )
        return [
            ResolvedSubject(
                type=SubjectType.DEPARTMENT,
                department_id=item.get("department_id"),
                department_name=(
                    item.get("complete_name") or item.get("name")
                ),
                source="odoo_lookup",
            )
            for item in self._items(data)
            if isinstance(item.get("department_id"), int)
        ]

    async def _request(
        self,
        *,
        method: str,
        path: str,
        actor: ActorContext,
        payload: dict[str, object],
    ) -> object:
        clean_payload = {
            key: value for key, value in payload.items() if value is not None
        }
        clean_payload["odoo_user_id"] = actor.odoo_user_id
        try:
            response = await self._client.request_registered_tool(
                method=method,
                path=path,
                request_id=f"subject-{uuid4()}",
                response_model=ToolResponse,
                payload=clean_payload,
            )
        except OdooRecordNotFoundError:
            return {"items": []}
        except OdooAccessDeniedError as error:
            raise SubjectLookupError("SUBJECT_ACCESS_DENIED") from error
        except OdooError as error:
            raise SubjectLookupError("SUBJECT_LOOKUP_FAILED") from error
        return response.root

    @staticmethod
    def _items(data: object) -> list[dict[str, object]]:
        if not isinstance(data, dict):
            return []
        items = data.get("items")
        if not isinstance(items, list):
            return []
        return [item for item in items if isinstance(item, dict)]

    @staticmethod
    def _relation_id(value: object) -> int | None:
        if isinstance(value, dict) and isinstance(value.get("id"), int):
            return cast(int, value["id"])
        return None

    @staticmethod
    def _relation_name(value: object) -> str | None:
        if not isinstance(value, dict):
            return None
        name = value.get("name") or value.get("display_name")
        return name if isinstance(name, str) else None


class SubjectResolver:
    """Resolve subjects only through an explicit allowlisted lookup provider."""

    def __init__(self, provider: SubjectLookupProvider | None = None) -> None:
        self._provider = provider

    async def resolve(
        self,
        mention: SubjectMention,
        actor: ActorContext,
    ) -> SubjectResolution:
        if mention.type is SubjectType.SELF:
            if actor.linked_employee_id is None:
                return SubjectResolution(
                    status=SubjectResolutionStatus.NOT_FOUND,
                    reason_code="SELF_EMPLOYEE_NOT_LINKED",
                )
            return SubjectResolution(
                status=SubjectResolutionStatus.RESOLVED,
                subject=ResolvedSubject(
                    type=SubjectType.SELF,
                    employee_id=actor.linked_employee_id,
                    source="trusted_context",
                ),
                reason_code="SUBJECT_RESOLVED",
            )
        if self._provider is None:
            return SubjectResolution(
                status=SubjectResolutionStatus.LOOKUP_UNAVAILABLE,
                reason_code="SUBJECT_LOOKUP_NOT_AVAILABLE",
            )
        try:
            if mention.type is SubjectType.EMPLOYEE:
                matches = await self._provider.search_employees(
                    name=mention.employee_name,
                    code=mention.employee_code,
                    actor=actor,
                )
            elif (
                mention.type is SubjectType.DEPARTMENT
                and mention.department_name is not None
            ):
                matches = await self._provider.search_departments(
                    name=mention.department_name,
                    actor=actor,
                )
            else:
                return SubjectResolution(
                    status=SubjectResolutionStatus.NOT_FOUND,
                    reason_code="SUBJECT_MENTION_INCOMPLETE",
                )
        except SubjectLookupError as error:
            return SubjectResolution(
                status=SubjectResolutionStatus.LOOKUP_UNAVAILABLE,
                reason_code=error.reason_code,
            )
        if not matches:
            return SubjectResolution(
                status=SubjectResolutionStatus.NOT_FOUND,
                reason_code="SUBJECT_NOT_FOUND",
            )
        if len(matches) == 1:
            return SubjectResolution(
                status=SubjectResolutionStatus.RESOLVED,
                subject=matches[0].model_copy(update={"source": "odoo_lookup"}),
                reason_code="SUBJECT_RESOLVED",
            )
        return SubjectResolution(
            status=SubjectResolutionStatus.AMBIGUOUS,
            options=[
                SubjectLookupOption(
                    value=(
                        match.employee_id
                        or match.department_id
                        or match.company_id
                        or 0
                    ),
                    label=(
                        match.employee_name
                        or match.department_name
                        or "Không xác định"
                    ),
                    employee_code=match.employee_code,
                )
                for match in matches
                if (
                    match.employee_id
                    or match.department_id
                    or match.company_id
                )
            ],
            reason_code="SUBJECT_AMBIGUOUS",
        )
