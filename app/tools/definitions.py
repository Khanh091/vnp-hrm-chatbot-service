from __future__ import annotations

from datetime import date
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, RootModel, model_validator


class Domain(str, Enum):
    PROFILE = "profile"
    ATTENDANCE = "attendance"
    LEAVE = "leave"


class RouteType(str, Enum):
    QUERY = "query"
    COMMAND = "command"


class Operation(str, Enum):
    GET = "get"
    LIST = "list"
    CHECK = "check"
    CREATE = "create"
    UPDATE = "update"
    CANCEL = "cancel"


class RiskLevel(str, Enum):
    READ = "read"
    SENSITIVE_READ = "sensitive_read"
    WRITE = "write"
    HIGH_RISK_WRITE = "high_risk_write"


class HttpMethod(str, Enum):
    GET = "GET"
    POST = "POST"
    PUT = "PUT"


class SubjectScope(str, Enum):
    SELF = "self"


class ToolArguments(BaseModel):
    """Base class for untrusted arguments selected from the user request."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class NoArguments(ToolArguments):
    pass


class AttendanceDailyArguments(ToolArguments):
    date: date


class DateRangeArguments(ToolArguments):
    date_from: date
    date_to: date

    @model_validator(mode="after")
    def validate_range(self) -> DateRangeArguments:
        if self.date_from > self.date_to:
            raise ValueError("date_from must not be after date_to")
        if (self.date_to - self.date_from).days > 366:
            raise ValueError("date range must not exceed 367 days")
        return self


class LeaveBalanceArguments(ToolArguments):
    year: int = Field(ge=1900, le=2200)
    leave_type_id: int | None = Field(default=None, gt=0)


class LeaveHistoryArguments(DateRangeArguments):
    state: Literal["draft", "wait_approve", "approve", "reject"] | None = None


class LeaveRequestStatusArguments(ToolArguments):
    request_id: int = Field(gt=0)


class LeavePeriodArguments(DateRangeArguments):
    leave_type_id: int = Field(gt=0)
    request_unit: Literal["day", "half_day", "hour"] = "day"
    half_day_period: Literal["first_half", "second_half"] | None = None
    time_from: float | None = Field(default=None, ge=0, lt=24)
    time_to: float | None = Field(default=None, ge=0, lt=24)

    @model_validator(mode="after")
    def validate_unit_details(self) -> LeavePeriodArguments:
        if self.request_unit == "half_day":
            if self.half_day_period is None:
                raise ValueError("half_day_period is required for half_day")
        elif self.half_day_period is not None:
            raise ValueError("half_day_period is only valid for half_day")

        if self.request_unit == "hour":
            if self.time_from is None or self.time_to is None:
                raise ValueError("time_from and time_to are required for hour")
            if self.time_from >= self.time_to:
                raise ValueError("time_from must be before time_to")
        elif self.time_from is not None or self.time_to is not None:
            raise ValueError("time fields are only valid for hour")
        return self


class LeaveCommandArguments(LeavePeriodArguments):
    reason: str = Field(min_length=1, max_length=2000)
    idempotency_key: str = Field(min_length=1, max_length=128)


class LeaveUpdateArguments(LeaveCommandArguments):
    request_id: int = Field(gt=0)


class LeaveCancelArguments(ToolArguments):
    request_id: int = Field(gt=0)
    idempotency_key: str = Field(min_length=1, max_length=128)


class TrustedExecutionContext(BaseModel):
    """Server-authenticated values that can never come from tool arguments."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    odoo_user_id: int = Field(gt=0)
    employee_id: int | None = Field(default=None, gt=0)
    company_id: int | None = Field(default=None, gt=0)
    timezone: str = Field(default="Asia/Ho_Chi_Minh", min_length=1, max_length=64)
    language: str | None = Field(default=None, max_length=32)
    conversation_id: str = Field(default="unknown", min_length=1, max_length=128)
    request_id: str = Field(min_length=1, max_length=128)


class ValidatedToolExecution(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    tool_name: str
    arguments: dict[str, Any]
    trusted_context: TrustedExecutionContext
    confirmation_granted: bool = False


class ToolResponse(RootModel[Any]):
    """Typed boundary for endpoint data whose detailed shape is owned by Odoo."""


class ToolDefinition(BaseModel):
    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    name: str
    domain: Domain
    capability: str
    operation: Operation
    route_type: RouteType
    risk_level: RiskLevel
    description: str
    endpoint: str
    http_method: HttpMethod
    argument_schema: type[BaseModel]
    response_schema: type[BaseModel] | None = ToolResponse
    examples: tuple[str, ...]
    negative_examples: tuple[str, ...]
    supported_scopes: tuple[SubjectScope, ...] = (SubjectScope.SELF,)
    requires_confirmation: bool = False
    enabled: bool = True
    version: str = "1.0"
    path_arguments: tuple[str, ...] = ()
    sensitive: bool = False


class ToolExecutionResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    tool_name: str
    success: bool
    data: Any | None = None
    error_code: str | None = None
    error_message: str | None = None
    latency_ms: float = Field(ge=0)
