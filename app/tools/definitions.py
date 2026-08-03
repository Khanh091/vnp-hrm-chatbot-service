from __future__ import annotations

from datetime import date
from enum import Enum
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, RootModel, model_validator

from app.routing.taxonomy import Intent, QueryRoute, SubjectType
from app.routing.taxonomy import Operation as QueryOperation

if TYPE_CHECKING:
    from app.context.actor import ActorContext


class Domain(str, Enum):
    PROFILE = "profile"
    ATTENDANCE = "attendance"
    LEAVE = "leave"
    DIRECTORY = "directory"
    REPORTING = "reporting"


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
    FAMILY_RELATIONS_READ = "family_relations_read"
    PERSONAL_BACKGROUND_READ = "personal_background_read"
    FAMILY_ECONOMY_READ = "family_economy_read"
    HEALTH_READ = "health_read"
    WRITE = "write"
    HIGH_RISK_WRITE = "high_risk_write"


SENSITIVE_READ_RISK_LEVELS = frozenset(
    {
        RiskLevel.SENSITIVE_READ,
        RiskLevel.FAMILY_RELATIONS_READ,
        RiskLevel.PERSONAL_BACKGROUND_READ,
        RiskLevel.FAMILY_ECONOMY_READ,
        RiskLevel.HEALTH_READ,
    }
)


class HttpMethod(str, Enum):
    GET = "GET"
    POST = "POST"
    PUT = "PUT"
    PATCH = "PATCH"


class SubjectScope(str, Enum):
    SELF = "self"
    NAMED_EMPLOYEE = "named_employee"
    DEPARTMENT = "department"
    COMPANY = "company"


class ToolArguments(BaseModel):
    """Base class for untrusted arguments selected from the user request."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class NoArguments(ToolArguments):
    pass


class EmployeeSearchArguments(ToolArguments):
    name: str | None = Field(default=None, min_length=1, max_length=256)
    employee_code: str | None = Field(
        default=None,
        min_length=1,
        max_length=128,
    )
    department_id: int | None = Field(default=None, gt=0)
    limit: int = Field(default=10, gt=0, le=50)

    @model_validator(mode="after")
    def require_search_criterion(self) -> EmployeeSearchArguments:
        if not (self.name or self.employee_code or self.department_id):
            raise ValueError("at least one employee search criterion is required")
        return self


class DepartmentSearchArguments(ToolArguments):
    name: str = Field(min_length=1, max_length=256)
    limit: int = Field(default=10, gt=0, le=50)


class DepartmentListArguments(ToolArguments):
    query: str | None = Field(default=None, min_length=1, max_length=256)
    company_id: int | None = Field(default=None, gt=0)
    active: bool = True
    limit: int = Field(default=50, gt=0, le=100)
    offset: int = Field(default=0, ge=0)


class EmployeeSubjectArguments(ToolArguments):
    employee_id: int = Field(gt=0)


class DepartmentEmployeesArguments(ToolArguments):
    department_id: int = Field(gt=0)
    active: bool = True
    employee_type: int | None = Field(default=None, gt=0)
    job_title: int | None = Field(default=None, gt=0)
    limit: int = Field(default=50, gt=0, le=100)
    offset: int = Field(default=0, ge=0)


class EmployeeCertificateSearchArguments(ToolArguments):
    certificate_query: str = Field(min_length=1, max_length=256)
    certificate_type: str | None = Field(default=None, min_length=1, max_length=128)
    valid_on: date | None = None
    department_id: int | None = Field(default=None, gt=0)
    company_id: int | None = Field(default=None, gt=0)
    active_employee_only: bool = True
    limit: int = Field(default=20, ge=1, le=100)
    offset: int = Field(default=0, ge=0)


class ContractExpiringArguments(ToolArguments):
    date_from: date | None = None
    date_to: date | None = None
    within_days: int | None = Field(default=None, ge=0, le=366)
    department_id: int | None = Field(default=None, gt=0)
    company_id: int | None = Field(default=None, gt=0)
    contract_type_id: int | None = Field(default=None, gt=0)
    active_employee_only: bool = True
    limit: int = Field(default=50, ge=1, le=100)
    offset: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def validate_period(self) -> ContractExpiringArguments:
        has_dates = self.date_from is not None or self.date_to is not None
        if self.within_days is not None and has_dates:
            raise ValueError("within_days cannot be combined with date range")
        if self.within_days is None:
            if self.date_from is None or self.date_to is None:
                raise ValueError(
                    "provide within_days or both date_from and date_to"
                )
            if self.date_from > self.date_to:
                raise ValueError("date_from must not be after date_to")
        return self


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


class LeaveActionableArguments(ToolArguments):
    action: Literal["update", "cancel"]


class LeaveRequestDetailsArguments(ToolArguments):
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


class LeaveUpdateChanges(ToolArguments):
    date_from: date | None = None
    date_to: date | None = None
    leave_type_id: int | None = Field(default=None, gt=0)
    reason: str | None = Field(default=None, min_length=1, max_length=2000)

    @model_validator(mode="after")
    def require_changed_field(self) -> LeaveUpdateChanges:
        if not self.model_fields_set:
            raise ValueError("at least one changed field is required")
        if self.date_from and self.date_to and self.date_from > self.date_to:
            raise ValueError("date_from must not be after date_to")
        return self


class LeaveUpdateArguments(ToolArguments):
    request_id: int = Field(gt=0)
    changes: LeaveUpdateChanges
    idempotency_key: str = Field(min_length=1, max_length=128)


class LeaveCancelArguments(ToolArguments):
    request_id: int = Field(gt=0)
    idempotency_key: str = Field(min_length=1, max_length=128)


class TrustedExecutionContext(BaseModel):
    """Server-authenticated values that can never come from tool arguments."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    odoo_user_id: int = Field(gt=0)
    employee_id: int | None = Field(default=None, gt=0)
    company_id: int | None = Field(default=None, gt=0)
    department_id: int | None = Field(default=None, gt=0)
    company_ids: tuple[int, ...] = ()
    group_codes: tuple[str, ...] = ()
    capabilities: tuple[str, ...] = ()
    timezone: str = Field(default="Asia/Ho_Chi_Minh", min_length=1, max_length=64)
    language: str | None = Field(default=None, max_length=32)
    conversation_id: str = Field(default="unknown", min_length=1, max_length=128)
    request_id: str = Field(min_length=1, max_length=128)

    @property
    def linked_employee_id(self) -> int | None:
        return self.employee_id

    @property
    def actor_context(self) -> ActorContext:
        from app.context.actor import ActorContext

        return ActorContext(
            odoo_user_id=self.odoo_user_id,
            company_ids=self.company_ids,
            group_codes=self.group_codes,
            capabilities=self.capabilities,
            locale=self.language or "vi_VN",
            timezone=self.timezone,
            linked_employee_id=self.employee_id,
            department_id=self.department_id,
        )


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
    capability_name: str = ""
    intent: Intent | None = None
    intents: frozenset[Intent] = frozenset()
    route: QueryRoute | None = None
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
    supported_subject_types: tuple[SubjectType, ...] = ()
    requires_confirmation: bool = False
    enabled: bool = True
    version: str = "1.0"
    path_arguments: tuple[str, ...] = ()
    sensitive: bool = False
    required_actor_capability: str | None = None

    @model_validator(mode="after")
    def derive_routing_metadata(self) -> ToolDefinition:
        from app.routing.capabilities import (
            CAPABILITY_REGISTRY,
            common_capability_names,
        )

        intent_value = {
            "leave.request.create": Intent.LEAVE_CREATE,
            "leave.request.update": Intent.LEAVE_UPDATE,
            "leave.request.cancel": Intent.LEAVE_CANCEL,
            "attendance.missing_punch_summary": Intent.ATTENDANCE_MISSING_PUNCH,
        }.get(self.capability)
        if intent_value is None:
            try:
                intent_value = Intent(self.capability)
            except ValueError as error:
                raise ValueError(
                    f"tool capability has no registered intent: {self.capability}"
                ) from error
        expected_route = (
            QueryRoute.TASK
            if self.route_type is RouteType.COMMAND
            else QueryRoute.DATA_QUERY
        )
        declared_intents = self.intents or frozenset(
            {self.intent or intent_value}
        )
        if intent_value not in declared_intents:
            raise ValueError("tool capability intent must be declared")
        if self.intent is not None and self.intent not in declared_intents:
            raise ValueError("primary tool intent must be declared")
        if self.route is not None and self.route is not expected_route:
            raise ValueError("tool query route does not match route_type")
        capability_name = self.capability_name
        if not capability_name:
            common_names = common_capability_names(declared_intents)
            if len(common_names) != 1:
                raise ValueError(
                    "tool intents must resolve to one registered capability"
                )
            capability_name = next(iter(common_names))
        try:
            capability_definition = CAPABILITY_REGISTRY[capability_name]
        except KeyError as error:
            raise ValueError(
                f"tool capability is not registered: {capability_name}"
            ) from error
        if not declared_intents <= capability_definition.supported_intents:
            raise ValueError(
                "tool intents must be supported by its capability"
            )
        query_operation = {
            Operation.CREATE: QueryOperation.CREATE,
            Operation.UPDATE: QueryOperation.UPDATE,
            Operation.CANCEL: QueryOperation.CANCEL,
        }.get(self.operation, QueryOperation.READ)
        if query_operation is not capability_definition.operation:
            raise ValueError(
                "tool operation does not match its capability"
            )
        object.__setattr__(self, "intent", self.intent or intent_value)
        object.__setattr__(self, "intents", frozenset(declared_intents))
        object.__setattr__(self, "route", expected_route)
        if not self.supported_subject_types:
            subject_types = tuple(
                {
                    SubjectScope.SELF: SubjectType.SELF,
                    SubjectScope.NAMED_EMPLOYEE: SubjectType.EMPLOYEE,
                    SubjectScope.DEPARTMENT: SubjectType.DEPARTMENT,
                    SubjectScope.COMPANY: SubjectType.COMPANY,
                }[scope]
                for scope in self.supported_scopes
            )
            object.__setattr__(
                self,
                "supported_subject_types",
                subject_types,
            )
        if not set(self.supported_subject_types) <= set(
            capability_definition.supported_subject_types
        ):
            raise ValueError(
                "tool subject types must be supported by its capability"
            )
        object.__setattr__(self, "capability_name", capability_name)
        return self

    def supports_intent(self, intent: Intent) -> bool:
        return intent in self.intents

    @property
    def required_arguments(self) -> tuple[str, ...]:
        return tuple(
            name
            for name, field in self.argument_schema.model_fields.items()
            if field.is_required() and name != "idempotency_key"
        )

    @property
    def optional_arguments(self) -> tuple[str, ...]:
        return tuple(
            name
            for name, field in self.argument_schema.model_fields.items()
            if not field.is_required()
        )

    @property
    def tool_version(self) -> str:
        return self.version

    @property
    def query_operation(self) -> QueryOperation:
        return {
            Operation.CREATE: QueryOperation.CREATE,
            Operation.UPDATE: QueryOperation.UPDATE,
            Operation.CANCEL: QueryOperation.CANCEL,
        }.get(self.operation, QueryOperation.READ)


class ToolExecutionResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    tool_name: str
    success: bool
    data: Any | None = None
    error_code: str | None = None
    error_message: str | None = None
    latency_ms: float = Field(ge=0)
