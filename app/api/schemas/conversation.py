from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ConversationMessageResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int
    role: str
    type: str
    text: str | None
    data: dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime


class ConversationStateResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    conversation_id: str
    status: str
    pending_tool_name: str | None
    missing_arguments: list[str]
    ambiguous_arguments: list[str]
    expires_at: datetime
    messages: list[ConversationMessageResponse] = Field(default_factory=list)
    pending_clarification: dict[str, Any] | None = None
    pending_confirmation: dict[str, Any] | None = None
    data: dict[str, Any]
