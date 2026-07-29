from __future__ import annotations

from datetime import date as DateValue
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.routing.taxonomy import SubjectScope


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


class ResolvedSubject(BaseModel):
    """A subject resolved by trusted context, structured UI, or an Odoo lookup."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    scope: SubjectScope
    employee_id: int | None = Field(default=None, gt=0)
    employee_name: str | None = Field(default=None, max_length=200)
    employee_code: str | None = Field(default=None, max_length=100)
    source: str = Field(
        pattern=r"^(trusted_context|structured_option|odoo_lookup)$"
    )
