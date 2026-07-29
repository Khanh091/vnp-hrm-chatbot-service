from __future__ import annotations

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

from app.routing.taxonomy import (
    Intent,
    QueryRoute,
)
from app.routing.taxonomy import (
    Operation as RoutingOperation,
)
from app.routing.taxonomy import (
    SubjectScope as RoutingSubjectScope,
)
from app.tools.definitions import RiskLevel

Operation = RoutingOperation
SubjectScope = RoutingSubjectScope


class RouteType(str, Enum):
    STRUCTURED_QUERY = "structured_query"
    TRANSACTION = "transaction"
    DOCUMENT_QA = "document_qa"
    ANALYTICS = "analytics"
    EMPLOYEE_SEARCH = "employee_search"
    NAVIGATION = "navigation"
    GENERAL_CHAT = "general_chat"
    UNSUPPORTED = "unsupported"


class Domain(str, Enum):
    PROFILE = "profile"
    ATTENDANCE = "attendance"
    LEAVE = "leave"
    GENERAL = "general"


class NormalizedQuery(BaseModel):
    model_config = ConfigDict(frozen=True)

    original_text: str = Field(min_length=1, max_length=4000)
    normalized_text: str = Field(min_length=1, max_length=4000)


class RuleHints(BaseModel):
    model_config = ConfigDict(frozen=True)

    route_hint: RouteType | None = None
    domain_hint: Domain | None = None
    operation_hint: Operation | None = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    reason_code: str | None = Field(default=None, max_length=80)


class QueryClassification(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    route: QueryRoute
    domain: Domain | None = None
    intent: Intent | None = None
    operation: Operation = Operation.NONE
    secondary_domains: list[Domain] = Field(
        default_factory=list,
        exclude=True,
    )
    scope: SubjectScope = Field(
        default=SubjectScope.SELF,
        description="Đối tượng dữ liệu được hỏi, không quyết định quyền truy cập.",
    )
    confidence: float = Field(ge=0.0, le=1.0)
    reason_code: str | None = Field(
        default=None,
        max_length=80,
        pattern=r"^[A-Z][A-Z0-9_]*$",
        description="Mã UPPER_SNAKE_CASE ngắn, không phải explanation.",
    )

    @model_validator(mode="before")
    @classmethod
    def accept_legacy_classifier_shape(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        data = dict(value)
        legacy_route = data.pop("route_type", None)
        if "route" not in data and legacy_route is not None:
            data["route"] = {
                "structured_query": QueryRoute.DATA_QUERY,
                "analytics": QueryRoute.DATA_QUERY,
                "transaction": QueryRoute.TASK,
                "document_qa": QueryRoute.KNOWLEDGE,
                "general_chat": QueryRoute.GENERAL,
                "unsupported": QueryRoute.UNSUPPORTED,
            }.get(
                str(getattr(legacy_route, "value", legacy_route)),
                QueryRoute.UNSUPPORTED,
            )
        if "domain" not in data:
            data["domain"] = data.pop("primary_domain", None)
        else:
            data.pop("primary_domain", None)
        capability = data.pop("capability_hint", None)
        if "intent" not in data and capability:
            normalized = str(capability).replace("_", ".")
            aliases = {
                "contact.info": "profile.contact",
                "leave.request.create": "leave.create",
                "leave.request.update": "leave.update",
                "leave.request.cancel": "leave.cancel",
                "attendance.missing.punch.summary": "attendance.missing_punch",
            }
            candidate = aliases.get(normalized, normalized)
            if candidate in {item.value for item in Intent}:
                data["intent"] = candidate
        legacy_operation = data.pop("operation_hint", None)
        if "operation" not in data:
            operation = str(
                getattr(legacy_operation, "value", legacy_operation or "none")
            )
            data["operation"] = {
                "get": "read",
                "list": "read",
                "check": "read",
                "explain": "read",
                "search": "read",
                "navigate": "read",
                "summarize": "read",
            }.get(operation, operation)
        return data

    @field_validator("reason_code")
    @classmethod
    def normalize_reason_code(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            return None
        return normalized

    @property
    def route_type(self) -> RouteType:
        return {
            QueryRoute.DATA_QUERY: RouteType.STRUCTURED_QUERY,
            QueryRoute.TASK: RouteType.TRANSACTION,
            QueryRoute.KNOWLEDGE: RouteType.DOCUMENT_QA,
            QueryRoute.GENERAL: RouteType.GENERAL_CHAT,
            QueryRoute.UNSUPPORTED: RouteType.UNSUPPORTED,
            QueryRoute.UNSAFE: RouteType.UNSUPPORTED,
        }[self.route]

    @property
    def primary_domain(self) -> Domain:
        return self.domain or Domain.GENERAL

    @property
    def capability_hint(self) -> str | None:
        return self.intent.value if self.intent else None

    @property
    def operation_hint(self) -> Operation | None:
        return None if self.operation is Operation.NONE else self.operation


class ToolCandidate(BaseModel):
    model_config = ConfigDict(frozen=True)

    tool_name: str
    domain: Domain
    capability: str
    operation: Operation
    score: float = Field(ge=-1.0, le=1.0)
    rank: int = Field(gt=0)


class CandidateRetrievalRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    query: str = Field(min_length=1, max_length=4000)
    classification: QueryClassification
    top_k: int = Field(gt=0, le=100)
    fetch_k: int = Field(gt=0, le=500)
    min_score: float = Field(ge=-1.0, le=1.0)

    @field_validator("fetch_k")
    @classmethod
    def fetch_must_be_positive(cls, value: int) -> int:
        return value

    @property
    def effective_fetch_k(self) -> int:
        return max(self.fetch_k, self.top_k)


class RoutingStageTimings(BaseModel):
    model_config = ConfigDict(frozen=True)

    normalization_ms: float = Field(ge=0)
    classification_ms: float = Field(ge=0)
    embedding_ms: float = Field(ge=0)
    vector_search_ms: float = Field(ge=0)


class RoutingDebugResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    normalized_query: str
    classification: QueryClassification
    candidates: list[ToolCandidate]
    timings: RoutingStageTimings


class ToolSelection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    selected_tool: str | None = Field(default=None, max_length=64)
    confidence: float = Field(ge=0.0, le=1.0)
    scope: SubjectScope = SubjectScope.SELF
    extracted_arguments: dict[str, Any] = Field(default_factory=dict)
    missing_arguments: list[str] = Field(default_factory=list)
    ambiguous_arguments: list[str] = Field(default_factory=list)
    requires_clarification: bool = False
    clarification_question: str | None = Field(default=None, max_length=300)
    reason_code: str | None = Field(
        default=None,
        max_length=80,
        pattern=r"^[A-Z][A-Z0-9_]*$",
    )

    @model_validator(mode="after")
    def clarification_fields_are_consistent(self) -> ToolSelection:
        if self.requires_clarification and not self.clarification_question:
            raise ValueError("clarification_question is required")
        if not self.requires_clarification and self.clarification_question:
            raise ValueError("clarification_question must be null")
        return self


class ToolCandidateContext(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    tool_name: str
    domain: Domain
    capability: str
    operation: Operation
    route_type: RouteType
    risk_level: RiskLevel
    description: str
    required_arguments: list[str]
    optional_arguments: list[str]
    examples: list[str]
    negative_examples: list[str]
    supported_scopes: list[SubjectScope]
    requires_confirmation: bool
    score: float = Field(ge=-1.0, le=1.0)


class ConversationContext(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    conversation_id: str
    pending_tool: str | None = None
    collected_arguments: dict[str, Any] = Field(default_factory=dict)
    last_user_message: str | None = None


class ToolSelectorRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    original_query: str
    normalized_query: str
    classification: QueryClassification
    candidates: list[ToolCandidateContext]
    conversation_context: ConversationContext | None = None
    current_date: date
    timezone: str


class ResolvedDateRange(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    date_from: date
    date_to: date
    source_expression: str
    resolution_type: str


class ValidationIssueCategory(str, Enum):
    ROUTING = "routing"
    ARGUMENT = "argument"
    AUTHORIZATION = "authorization"
    SECURITY = "security"
    PROVIDER = "provider"
    BUSINESS = "business"

    @classmethod
    def _missing_(cls, value: object) -> ValidationIssueCategory | None:
        if not isinstance(value, str):
            return None
        legacy = {
            "arguments": cls.ARGUMENT,
            "confidence": cls.ROUTING,
            "policy": cls.AUTHORIZATION,
        }
        return legacy.get(value)


class ValidationIssue(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    code: str
    category: ValidationIssueCategory = ValidationIssueCategory.ROUTING
    field: str | None = None
    message: str


class RoutingValidationResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    valid: bool
    issues: list[ValidationIssue] = Field(default_factory=list)


class ArgumentValidationResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    valid: bool
    requires_clarification: bool = False
    normalized_arguments: dict[str, Any] = Field(default_factory=dict)
    missing_arguments: list[str] = Field(default_factory=list)
    ambiguous_arguments: list[str] = Field(default_factory=list)
    issues: list[ValidationIssue] = Field(default_factory=list)


class SecurityValidationResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    valid: bool
    issues: list[ValidationIssue] = Field(default_factory=list)


class ToolValidationResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    valid: bool
    can_execute: bool
    requires_clarification: bool
    requires_confirmation: bool
    normalized_arguments: dict[str, Any] = Field(default_factory=dict)
    errors: list[ValidationIssue] = Field(default_factory=list)
    routing: RoutingValidationResult | None = None
    arguments: ArgumentValidationResult | None = None
    security: SecurityValidationResult | None = None
