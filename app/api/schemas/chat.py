from datetime import date
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
from app.common.capability_outcomes import CapabilityOutcome
from app.orchestration.state import ChatResponseType, ChatStageTimings


class ChatActionType(str, Enum):
    CONFIRM = "confirm"
    CANCEL = "cancel"
    CANCEL_WORKFLOW = "cancel_workflow"


class ChatAction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: ChatActionType
    action_id: str | None = Field(
        default=None,
        min_length=40,
        max_length=64,
        pattern=r"^act-[0-9a-fA-F-]{36}$",
    )

    @model_validator(mode="after")
    def validate_action_id(self) -> "ChatAction":
        if (
            self.type in {ChatActionType.CONFIRM, ChatActionType.CANCEL}
            and self.action_id is None
        ):
            raise ValueError("action_id is required for pending actions")
        if (
            self.type is ChatActionType.CANCEL_WORKFLOW
            and self.action_id is not None
        ):
            raise ValueError("action_id is not used for workflow cancellation")
        return self


class ClarificationAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field: str = Field(min_length=1, max_length=128)
    value: str | int | float | bool
    label: str | None = Field(default=None, min_length=1, max_length=500)

    @field_validator("value")
    @classmethod
    def validate_value(
        cls,
        value: str | int | float | bool,
    ) -> str | int | float | bool:
        if isinstance(value, str):
            value = value.strip()
            if not value or len(value) > 500:
                raise ValueError(
                    "clarification value must be an integer or non-empty string"
                )
        return value


ChatClarification = ClarificationAnswer


class ClarificationInputType(str, Enum):
    SECTION_SELECT = "section_select"
    RESOURCE_SELECT = "resource_select"
    FIELD_SELECT = "field_select"
    RECORD_SELECT = "record_select"
    SINGLE_SELECT = "single_select"
    SEARCHABLE_SELECT = "searchable_select"
    DATE = "date"
    BOOLEAN = "boolean"
    TEXT = "text"
    NUMBER = "number"
    DATE_RANGE = "date_range"
    ATTACHMENT = "attachment"
    RESOURCE_FORM = "resource_form"
    RECORD_FORM = "record_form"
    EDIT_SUMMARY = "edit_summary"
    EDIT_SESSION_ACTIONS = "edit_session_actions"


class ClarificationOption(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: str
    label: str
    description: str | None = None


class ClarificationContract(BaseModel):
    model_config = ConfigDict(extra="forbid")

    input_type: ClarificationInputType
    slot_name: str
    options: list[ClarificationOption] | None = None
    min_date: date | None = None
    max_date: date | None = None
    initial_date: date | None = None


class StructuredAnswerType(str, Enum):
    OPTION_SELECT = "option_select"
    DATE_SELECT = "date_select"
    CONFIRM = "confirm"
    CANCEL = "cancel"
    PROFILE_FIELD_EDIT = "profile_field_edit"
    PROFILE_EDIT_ACTION = "profile_edit_action"


class StructuredAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: StructuredAnswerType
    slot_name: str | None = Field(default=None, min_length=1, max_length=128)
    selected_value: str | None = Field(default=None, min_length=1, max_length=500)
    display_label: str | None = Field(default=None, min_length=1, max_length=500)
    session_id: str | None = Field(default=None, min_length=1, max_length=128)
    field_key: str | None = Field(default=None, min_length=1, max_length=128)
    value: str | int | float | bool | None = None
    action: str | None = Field(default=None, min_length=1, max_length=32)

    @model_validator(mode="after")
    def validate_shape(self) -> "StructuredAnswer":
        if self.type in {
            StructuredAnswerType.OPTION_SELECT,
            StructuredAnswerType.DATE_SELECT,
        }:
            if not self.slot_name or not self.selected_value or not self.display_label:
                raise ValueError(
                    "slot_name, selected_value and display_label are required"
                )
        elif self.type is StructuredAnswerType.CONFIRM:
            if not self.selected_value:
                raise ValueError("selected_value action id is required")
            if self.slot_name is not None:
                raise ValueError("slot_name is not used for confirmation")
        elif self.slot_name is not None:
            raise ValueError("slot_name is not used for cancellation")
        if self.type is StructuredAnswerType.DATE_SELECT:
            try:
                date.fromisoformat(self.selected_value or "")
            except ValueError as error:
                raise ValueError("selected_value must be an ISO date") from error
        if self.type is StructuredAnswerType.PROFILE_FIELD_EDIT:
            if not self.session_id or not self.field_key:
                raise ValueError("session_id and field_key are required")
            if self.action is not None:
                raise ValueError("action is not used for field editing")
        if self.type is StructuredAnswerType.PROFILE_EDIT_ACTION:
            if not self.session_id or self.action not in {
                "finish", "cancel", "save_draft", "submit", "continue",
                "switch_save_draft", "switch_discard",
            }:
                raise ValueError("invalid profile edit action")
            if self.field_key is not None or self.value is not None:
                raise ValueError("field_key and value are not used for actions")
        return self


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str | None = Field(default=None, min_length=1, max_length=4000)
    conversation_id: str | None = Field(default=None, min_length=1, max_length=128)
    structured_answer: StructuredAnswer | None = None

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
            for item in (self.message, self.structured_answer)
        )
        if provided != 1:
            raise ValueError(
                "provide exactly one of message or structured_answer"
            )
        if self.structured_answer is not None and self.conversation_id is None:
            raise ValueError(
                "conversation_id is required for workflow continuations"
            )
        return self


class ChatResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    conversation_id: str
    type: ChatResponseType
    outcome: CapabilityOutcome | None = None
    answer: str | None
    data: dict[str, Any] | None
    timings: ChatStageTimings
    meta: ResponseMeta
