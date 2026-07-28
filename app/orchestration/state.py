from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from typing_extensions import TypedDict


class ChatResponseType(str, Enum):
    ANSWER = "answer"
    CLARIFICATION_REQUIRED = "clarification_required"
    CONFIRMATION_REQUIRED = "confirmation_required"
    ERROR = "error"
    UNSUPPORTED = "unsupported"


class TurnType(str, Enum):
    NEW_QUERY = "new_query"
    CLARIFICATION_ANSWER = "clarification_answer"
    CONFIRMATION_ACCEPT = "confirmation_accept"
    CONFIRMATION_CANCEL = "confirmation_cancel"


class WorkflowStatus(str, Enum):
    RUNNING = "running"
    CLARIFICATION_REQUIRED = "clarification_required"
    CONFIRMATION_REQUIRED = "confirmation_required"
    EXECUTE_READ = "execute_read"
    EXECUTE_WRITE = "execute_write"
    COMPLETED = "completed"
    FAILED = "failed"


class WorkflowIssue(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    code: str
    field: str | None = None


class GraphEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    type: str
    data: dict[str, Any] = Field(default_factory=dict)


class ChatGraphState(TypedDict, total=False):
    conversation_id: str
    request_id: str
    user_message: str | None
    action_type: str | None
    action_id: str | None
    normalized_query: str | None
    trusted_context: dict[str, Any]
    turn_type: TurnType
    workflow_status: WorkflowStatus
    conversation_status: str
    conversation_version: int
    classification: dict[str, Any]
    candidates: list[dict[str, Any]]
    candidate_contexts: list[dict[str, Any]]
    selection: dict[str, Any]
    validation: dict[str, Any]
    pending_tool_name: str | None
    collected_arguments: dict[str, Any]
    missing_arguments: list[str]
    ambiguous_arguments: list[str]
    workflow_data: dict[str, Any]
    pending_action_id: str | None
    pending_action: dict[str, Any]
    tool_result: dict[str, Any] | None
    response_type: ChatResponseType | None
    response_text: str | None
    response_data: dict[str, Any] | None
    workflow_issues: list[dict[str, Any]]
    current_step: int
    stage_timings: dict[str, float]
    graph_events: list[dict[str, Any]]


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
    normalization_ms: float = Field(default=0, ge=0)
    conversation_load_ms: float = Field(default=0, ge=0)
    turn_detection_ms: float = Field(default=0, ge=0)
    argument_merge_ms: float = Field(default=0, ge=0)
    pending_action_ms: float = Field(default=0, ge=0)
    odoo_execution_ms: float = Field(default=0, ge=0)
    conversation_persist_ms: float = Field(default=0, ge=0)


class ChatPipelineResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    conversation_id: str
    type: ChatResponseType
    answer: str | None = None
    data: dict[str, Any] | None = None
    timings: ChatStageTimings
