from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class ActorContext(BaseModel):
    """Authenticated requester context, never derived from chat text."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    odoo_user_id: int = Field(gt=0)
    company_ids: tuple[int, ...] = ()
    group_codes: tuple[str, ...] = ()
    capabilities: tuple[str, ...] = ()
    locale: str = Field(default="vi_VN", min_length=1, max_length=32)
    timezone: str = Field(
        default="Asia/Ho_Chi_Minh",
        min_length=1,
        max_length=64,
    )
    linked_employee_id: int | None = Field(default=None, gt=0)
    department_id: int | None = Field(default=None, gt=0)
