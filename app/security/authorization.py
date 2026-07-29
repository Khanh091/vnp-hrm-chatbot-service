from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.context.entities import ResolvedSubject
from app.routing.intent_tool_mapping import tool_supports_intent
from app.routing.schemas import SecurityValidationResult, ValidationIssue
from app.routing.schemas import ValidationIssueCategory as IssueCategory
from app.routing.taxonomy import Intent, Operation, SubjectScope
from app.tools.definitions import RiskLevel, TrustedExecutionContext
from app.tools.registry import ToolNotFoundError, ToolRegistry

_TRUSTED_FIELDS = {
    "odoo_user_id",
    "employee_id",
    "company_id",
    "conversation_id",
    "timezone",
    "language",
}
_FORBIDDEN_EXECUTION_FIELDS = {
    "endpoint",
    "url",
    "model",
    "odoo_model",
    "orm_domain",
    "sudo",
}


class AuthorizationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    tool_name: str = Field(min_length=1, max_length=128)
    intent: Intent
    operation: Operation
    scope: SubjectScope
    trusted_context: TrustedExecutionContext
    resolved_subject: ResolvedSubject | None = None


class AuthorizationDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    allowed: bool
    reason_code: str = Field(pattern=r"^[A-Z][A-Z0-9_]*$")
    source: Literal["fastapi_policy", "odoo"]


class AuthorizationPolicyService:
    """FastAPI pre-authorization only; Odoo remains the final authority."""

    def __init__(self, registry: ToolRegistry) -> None:
        self._registry = registry

    def validate_security(
        self,
        arguments: dict[str, object],
        *,
        rejected_trusted_fields: list[str] | tuple[str, ...] = (),
    ) -> SecurityValidationResult:
        issues: list[ValidationIssue] = []
        injected = sorted(
            set(rejected_trusted_fields)
            | (_TRUSTED_FIELDS.intersection(arguments))
        )
        for field in injected:
            issues.append(
                ValidationIssue(
                    code="TRUSTED_FIELD_INJECTION",
                    category=IssueCategory.SECURITY,
                    field=field,
                    message="Trusted execution fields cannot come from user input.",
                )
            )
        for field in sorted(_FORBIDDEN_EXECUTION_FIELDS.intersection(arguments)):
            issues.append(
                ValidationIssue(
                    code="SECURITY_REJECTED",
                    category=IssueCategory.SECURITY,
                    field=field,
                    message="Arbitrary execution metadata is forbidden.",
                )
            )
        return SecurityValidationResult(valid=not issues, issues=issues)

    def authorize(
        self,
        request: AuthorizationRequest,
        *,
        allowed_tools: set[str] | frozenset[str] | None = None,
        confirmation_granted: bool = False,
    ) -> AuthorizationDecision:
        if allowed_tools is not None and request.tool_name not in allowed_tools:
            return self._deny("TOOL_NOT_ALLOWED")
        try:
            tool = self._registry.get(request.tool_name)
        except ToolNotFoundError:
            return self._deny("TOOL_NOT_ALLOWED")
        if not tool.enabled:
            return self._deny("TOOL_NOT_ALLOWED")
        if (
            not tool_supports_intent(tool.name, request.intent)
            or tool.query_operation is not request.operation
        ):
            return self._deny("TOOL_OPERATION_NOT_ALLOWED")
        supported_scopes = {scope.value for scope in tool.supported_scopes}
        if request.scope.value not in supported_scopes:
            return self._deny("SCOPE_NOT_ALLOWED")
        if request.scope is SubjectScope.SELF:
            subject = request.resolved_subject
            if subject is not None:
                if subject.scope is not SubjectScope.SELF:
                    return self._deny("SCOPE_NOT_ALLOWED")
                trusted_employee = request.trusted_context.employee_id
                if (
                    subject.employee_id is not None
                    and trusted_employee is not None
                    and subject.employee_id != trusted_employee
                ):
                    return self._deny("SUBJECT_CONTEXT_MISMATCH")
        elif request.scope is SubjectScope.NAMED_EMPLOYEE:
            subject = request.resolved_subject
            if (
                subject is None
                or subject.scope is not SubjectScope.NAMED_EMPLOYEE
                or subject.source not in {"structured_option", "odoo_lookup"}
            ):
                return self._deny("SUBJECT_NOT_RESOLVED")
        is_write = tool.risk_level in {
            RiskLevel.WRITE,
            RiskLevel.HIGH_RISK_WRITE,
        }
        if is_write and not confirmation_granted:
            return self._deny("WRITE_CONFIRMATION_REQUIRED")
        if not is_write and confirmation_granted:
            return self._deny("TOOL_OPERATION_NOT_ALLOWED")
        return AuthorizationDecision(
            allowed=True,
            reason_code="POLICY_PRECHECK_PASSED",
            source="fastapi_policy",
        )

    @staticmethod
    def _deny(reason_code: str) -> AuthorizationDecision:
        return AuthorizationDecision(
            allowed=False,
            reason_code=reason_code,
            source="fastapi_policy",
        )
