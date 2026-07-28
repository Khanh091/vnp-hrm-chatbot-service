from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class ConversationStateResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    conversation_id: str
    status: str
    pending_tool_name: str | None
    missing_arguments: list[str]
    ambiguous_arguments: list[str]
    expires_at: datetime
    data: dict[str, Any]
