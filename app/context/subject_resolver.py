from __future__ import annotations

from enum import Enum
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from app.context.actor import ActorContext
from app.context.entities import ResolvedSubject, SubjectMention
from app.routing.taxonomy import SubjectType


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
