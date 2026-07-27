from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.api.schemas.common import ApiResponse


class UserContextRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    odoo_user_id: int = Field(gt=0)


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


class ValidatedUserContext(BaseModel):
    user_id: int
    employee_id: int
    company_id: int
    department_id: int | None
    timezone: str
    language: str


class ChatAcceptedData(BaseModel):
    conversation_id: str
    answer: str
    user_context: ValidatedUserContext


ChatResponse = ApiResponse[ChatAcceptedData]
