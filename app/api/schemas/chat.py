from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.api.schemas.common import ResponseMeta
from app.orchestration.state import ChatResponseType, ChatStageTimings


class UserContextRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    odoo_user_id: int = Field(
        gt=0,
        description=(
            "Development/proxy-only identifier; production ingress must "
            "authenticate the Odoo proxy before trusting it."
        ),
    )


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str = Field(min_length=1, max_length=4000)
    conversation_id: str | None = Field(default=None, min_length=1, max_length=128)
    user_context: UserContextRequest

    @field_validator("message")
    @classmethod
    def message_must_not_be_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("message must not be blank")
        return value


class ChatResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    conversation_id: str
    type: ChatResponseType
    answer: str | None
    data: dict[str, Any] | None
    timings: ChatStageTimings
    meta: ResponseMeta
