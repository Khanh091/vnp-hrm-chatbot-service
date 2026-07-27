from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator


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


class Operation(str, Enum):
    GET = "get"
    LIST = "list"
    CHECK = "check"
    CREATE = "create"
    UPDATE = "update"
    CANCEL = "cancel"
    EXPLAIN = "explain"
    SEARCH = "search"
    NAVIGATE = "navigate"
    SUMMARIZE = "summarize"


class SubjectScope(str, Enum):
    SELF = "self"
    NAMED_EMPLOYEE = "named_employee"
    DIRECT_REPORTS = "direct_reports"
    DEPARTMENT = "department"
    COMPANY = "company"
    UNKNOWN = "unknown"


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

    route_type: RouteType = Field(
        description="Mục đích xử lý của toàn bộ câu hỏi; không phải domain.",
    )
    primary_domain: Domain = Field(
        description="Domain HRM chính; không phải route.",
    )
    secondary_domains: list[Domain] = Field(
        default_factory=list,
        description="Các domain phụ thực sự cần làm ngữ cảnh.",
    )
    capability_hint: str | None = Field(
        default=None,
        max_length=80,
        pattern=r"^[a-z][a-z0-9_]*$",
        description="Nhãn năng lực snake_case ngắn; tuyệt đối không phải tên tool.",
    )
    operation_hint: Operation | None = Field(
        default=None,
        description="Thao tác người dùng muốn thực hiện.",
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

    @field_validator("secondary_domains")
    @classmethod
    def unique_secondary_domains(cls, value: list[Domain]) -> list[Domain]:
        return list(dict.fromkeys(value))

    @field_validator("capability_hint", "reason_code")
    @classmethod
    def reject_long_explanations(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            return None
        return normalized


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
