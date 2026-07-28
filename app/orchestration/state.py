from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ChatResponseType(str, Enum):
    ANSWER = "answer"
    CLARIFICATION_REQUIRED = "clarification_required"
    CONFIRMATION_REQUIRED = "confirmation_required"
    ERROR = "error"
    UNSUPPORTED = "unsupported"


class ChatStageTimings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    classification_ms: float = Field(default=0, ge=0)
    candidate_retrieval_ms: float = Field(default=0, ge=0)
    tool_selection_ms: float = Field(default=0, ge=0)
    argument_resolution_ms: float = Field(default=0, ge=0)
    validation_ms: float = Field(default=0, ge=0)
    execution_ms: float = Field(default=0, ge=0)
    response_formatting_ms: float = Field(default=0, ge=0)
    total_ms: float = Field(default=0, ge=0)


class ChatPipelineResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    conversation_id: str
    type: ChatResponseType
    answer: str | None = None
    data: dict[str, Any] | None = None
    timings: ChatStageTimings
