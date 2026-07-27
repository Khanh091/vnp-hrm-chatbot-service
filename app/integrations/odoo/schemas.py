from datetime import datetime

from pydantic import BaseModel, Field, JsonValue


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
    employee_id: int
    company_id: int
    department_id: int | None
    timezone: str
    language: str


class CurrentUserContextRequest(BaseModel):
    odoo_user_id: int = Field(gt=0)
