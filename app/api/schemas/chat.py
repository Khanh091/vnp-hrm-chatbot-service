from enum import Enum
from typing import Any

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from app.api.schemas.common import ResponseMeta
from app.orchestration.state import ChatResponseType, ChatStageTimings


class ChatActionType(str, Enum):
    CONFIRM = "confirm"
    CANCEL = "cancel"


class ChatAction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: ChatActionType
    action_id: str = Field(
        min_length=40,
        max_length=64,
        pattern=r"^act-[0-9a-fA-F-]{36}$",
    )


class ChatClarification(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field: str = Field(min_length=1, max_length=128)
    value: int | str
    label: str = Field(min_length=1, max_length=500)

    @field_validator("value")
    @classmethod
    def validate_value(cls, value: int | str) -> int | str:
        if isinstance(value, bool):
            raise ValueError(
                "clarification value must be an integer or non-empty string"
            )
        if isinstance(value, str):
            value = value.strip()
            if not value or len(value) > 500:
                raise ValueError(
                    "clarification value must be an integer or non-empty string"
                )
        return value


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str | None = Field(default=None, min_length=1, max_length=4000)
    conversation_id: str | None = Field(default=None, min_length=1, max_length=128)
    action: ChatAction | None = None
    clarification: ChatClarification | None = None

    @field_validator("message")
    @classmethod
    def message_must_not_be_blank(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("message must not be blank")
        return value

    @model_validator(mode="after")
    def exactly_one_input(self) -> "ChatRequest":
        provided = sum(
            item is not None
            for item in (self.message, self.action, self.clarification)
        )
        if provided != 1:
            raise ValueError(
                "provide exactly one of message, action, or clarification"
            )
        if (
            self.action is not None or self.clarification is not None
        ) and self.conversation_id is None:
            raise ValueError(
                "conversation_id is required for workflow continuations"
            )
        return self


class ChatResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    conversation_id: str
    type: ChatResponseType
    answer: str | None
    data: dict[str, Any] | None
    timings: ChatStageTimings
    meta: ResponseMeta
