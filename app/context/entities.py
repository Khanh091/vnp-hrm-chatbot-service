from __future__ import annotations

from datetime import date as DateValue
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.routing.taxonomy import SubjectScope, SubjectType


class TemporalEntities(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    date: DateValue | str | None = None
    date_from: DateValue | str | None = None
    date_to: DateValue | str | None = None
    month: int | None = Field(default=None, ge=1, le=12)
    year: int | None = Field(default=None, ge=1900, le=2200)
    quarter: int | None = Field(default=None, ge=1, le=4)
    time_range: str | None = Field(default=None, max_length=200)


class BusinessEntities(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    employee_name: str | None = Field(default=None, max_length=200)
    employee_code: str | None = Field(default=None, max_length=100)
    department_name: str | None = Field(default=None, max_length=200)
    leave_type_text: str | None = Field(default=None, max_length=200)
    leave_request_code: str | None = Field(default=None, max_length=100)
    contract_code: str | None = Field(default=None, max_length=100)
    reason: str | None = Field(default=None, max_length=2000)


class EntityAmbiguity(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    field: str = Field(min_length=1, max_length=100)
    expression: str = Field(min_length=1, max_length=300)
    reason_code: str = Field(
        min_length=1,
        max_length=100,
        pattern=r"^[A-Z][A-Z0-9_]*$",
    )
    options: list[dict[str, Any]] = Field(default_factory=list)


class ExtractedEntities(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    temporal: TemporalEntities = Field(default_factory=TemporalEntities)
    business: BusinessEntities = Field(default_factory=BusinessEntities)
    ambiguities: list[EntityAmbiguity] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def reject_untrusted_ids(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        forbidden = {
            "employee_id",
            "leave_type_id",
            "odoo_user_id",
            "company_id",
        }
        if forbidden.intersection(value):
            raise ValueError("technical IDs are not extractable entities")
        return value


class SubjectMention(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    type: SubjectType
    employee_name: str | None = Field(default=None, max_length=200)
    employee_code: str | None = Field(default=None, max_length=100)
    department_name: str | None = Field(default=None, max_length=200)
    date_reference: DateValue | str | None = None
    ordinal_reference: int | None = Field(default=None, gt=0)
    recency_reference: Literal[
        "latest",
        "previous",
        "first",
        "last",
    ] | None = None


class ResolvedSubject(BaseModel):
    """A subject resolved by trusted context, structured UI, or an Odoo lookup."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    type: SubjectType
    employee_id: int | None = Field(default=None, gt=0)
    employee_code: str | None = Field(default=None, max_length=100)
    employee_name: str | None = Field(default=None, max_length=200)
    department_id: int | None = Field(default=None, gt=0)
    department_name: str | None = Field(default=None, max_length=200)
    company_id: int | None = Field(default=None, gt=0)
    source: str = Field(
        default="odoo_lookup",
        pattern=r"^(trusted_context|structured_option|odoo_lookup)$"
    )

    @model_validator(mode="before")
    @classmethod
    def accept_legacy_scope(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        data = dict(value)
        scope = data.pop("scope", None)
        if "type" not in data and scope is not None:
            scope_value = str(getattr(scope, "value", scope))
            data["type"] = {
                SubjectScope.SELF.value: SubjectType.SELF,
                SubjectScope.NAMED_EMPLOYEE.value: SubjectType.EMPLOYEE,
                SubjectScope.DEPARTMENT.value: SubjectType.DEPARTMENT,
                SubjectScope.COMPANY.value: SubjectType.COMPANY,
                SubjectScope.GENERAL.value: SubjectType.GENERAL,
            }.get(scope_value, SubjectType.GENERAL)
        return data

    @property
    def scope(self) -> SubjectScope:
        return {
            SubjectType.SELF: SubjectScope.SELF,
            SubjectType.EMPLOYEE: SubjectScope.NAMED_EMPLOYEE,
            SubjectType.DEPARTMENT: SubjectScope.DEPARTMENT,
            SubjectType.COMPANY: SubjectScope.COMPANY,
            SubjectType.GENERAL: SubjectScope.GENERAL,
        }[self.type]
