from datetime import datetime

from pydantic import AliasChoices, BaseModel, Field, JsonValue


class OdooMeta(BaseModel):
    request_id: str
    timestamp: datetime


class OdooEnvelope(BaseModel):
    success: bool
    code: str
    message: str
    data: JsonValue | None = None
    details: dict[str, JsonValue] = Field(default_factory=dict)
    meta: OdooMeta


class OdooHealthData(BaseModel):
    service: str
    version: str


class OdooUserContext(BaseModel):
    user_id: int
    employee_id: int | None = Field(
        default=None,
        validation_alias=AliasChoices("employee_id", "linked_employee_id"),
    )
    company_id: int
    company_ids: tuple[int, ...] = ()
    group_codes: tuple[str, ...] = ()
    capabilities: tuple[str, ...] = ()
    department_id: int | None
    timezone: str
    language: str


class CurrentUserContextRequest(BaseModel):
    odoo_user_id: int = Field(gt=0)
