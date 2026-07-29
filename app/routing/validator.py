from __future__ import annotations

from secrets import token_urlsafe
from typing import Any

from pydantic import ValidationError

from app.config import Settings
from app.routing.argument_resolver import ArgumentResolution
from app.routing.schemas import (
    ArgumentValidationResult,
    QueryClassification,
    RouteType,
    RoutingValidationResult,
    SecurityValidationResult,
    ToolCandidateContext,
    ToolSelection,
    ToolValidationResult,
    ValidationIssue,
    ValidationIssueCategory,
)
from app.tools.definitions import RiskLevel
from app.tools.definitions import RouteType as ToolRouteType
from app.tools.registry import ToolNotFoundError, ToolRegistry


class ToolSelectionValidator:
    """Deterministic routing, argument, and security validation.

    Scope/ACL decisions deliberately live in AuthorizationPolicyService and Odoo.
    """

    def __init__(self, registry: ToolRegistry, settings: Settings) -> None:
        self._registry = registry
        self._read_threshold = settings.tool_selection_min_confidence
        self._sensitive_threshold = (
            settings.sensitive_tool_selection_min_confidence
        )
        self._write_threshold = settings.write_tool_selection_min_confidence
        self._min_score = settings.tool_min_score
        self._min_margin = settings.tool_min_margin

    def validate(
        self,
        selection: ToolSelection,
        resolution: ArgumentResolution,
        *,
        classification: QueryClassification,
        candidates: list[ToolCandidateContext],
    ) -> ToolValidationResult:
        issues: list[ValidationIssue] = []
        candidate_map = {item.tool_name: item for item in candidates}
        if selection.selected_tool is None:
            return self._failure("NO_MATCHING_TOOL", ValidationIssueCategory.ROUTING)
        candidate = candidate_map.get(selection.selected_tool)
        if candidate is None:
            return self._failure(
                "TOOL_NOT_ALLOWED",
                ValidationIssueCategory.SECURITY,
                field="selected_tool",
            )
        try:
            tool = self._registry.get(selection.selected_tool)
        except ToolNotFoundError:
            return self._failure(
                "TOOL_NOT_REGISTERED",
                ValidationIssueCategory.ROUTING,
                field="selected_tool",
            )

        if not tool.enabled:
            issues.append(
                self._issue(
                    "TOOL_DISABLED",
                    ValidationIssueCategory.ROUTING,
                    "selected_tool",
                )
            )
        if tool.domain.value != classification.primary_domain.value:
            issues.append(
                self._issue(
                    "DOMAIN_MISMATCH",
                    ValidationIssueCategory.ROUTING,
                    "selected_tool",
                )
            )
        expected_transaction = classification.route_type is RouteType.TRANSACTION
        if expected_transaction != (tool.route_type is ToolRouteType.COMMAND):
            issues.append(
                self._issue(
                    "ROUTE_MISMATCH",
                    ValidationIssueCategory.ROUTING,
                    "selected_tool",
                )
            )
        if (
            classification.intent is not None
            and tool.intent is not classification.intent
        ):
            issues.append(
                self._issue(
                    "INTENT_MISMATCH",
                    ValidationIssueCategory.ROUTING,
                    "selected_tool",
                )
            )
        if tool.query_operation is not classification.operation:
            issues.append(
                self._issue(
                    "OPERATION_MISMATCH",
                    ValidationIssueCategory.ROUTING,
                    "selected_tool",
                )
            )

        threshold = self._threshold(tool.risk_level)
        low_confidence = selection.confidence < threshold
        if low_confidence:
            issues.append(
                self._issue(
                    "LOW_CONFIDENCE",
                    ValidationIssueCategory.ROUTING,
                    "confidence",
                )
            )
        scores = sorted((item.score for item in candidates), reverse=True)
        if (
            len(scores) > 1
            and scores[0] - scores[1] < self._min_margin
            and selection.confidence < min(1.0, threshold + 0.05)
        ):
            issues.append(
                self._issue(
                    "ROUTING_AMBIGUOUS",
                    ValidationIssueCategory.ROUTING,
                    "score",
                )
            )
        for field in resolution.rejected_trusted_fields:
            issues.append(
                self._issue(
                    "TRUSTED_FIELD_INJECTION",
                    ValidationIssueCategory.SECURITY,
                    field,
                )
            )
        for field in resolution.missing_arguments:
            issues.append(
                self._issue(
                    "MISSING_ARGUMENT",
                    ValidationIssueCategory.ARGUMENT,
                    field,
                )
            )
        for field in resolution.ambiguous_arguments:
            issues.append(
                self._issue(
                    "AMBIGUOUS_ARGUMENT",
                    ValidationIssueCategory.ARGUMENT,
                    field,
                )
            )

        clarification = bool(
            resolution.missing_arguments
            or resolution.ambiguous_arguments
            or selection.requires_clarification
            or low_confidence
            or any(issue.code == "ROUTING_AMBIGUOUS" for issue in issues)
        )
        normalized: dict[str, Any] = dict(resolution.arguments)
        is_write = tool.risk_level in {
            RiskLevel.WRITE,
            RiskLevel.HIGH_RISK_WRITE,
        }
        if is_write and not clarification:
            normalized.setdefault("idempotency_key", f"chat-{token_urlsafe(18)}")
        if not clarification:
            try:
                validated = tool.argument_schema.model_validate(normalized)
                normalized = validated.model_dump(mode="json")
            except ValidationError as error:
                for item in error.errors():
                    error_field = (
                        str(item["loc"][0]) if item.get("loc") else None
                    )
                    issues.append(
                        self._issue(
                            "INVALID_ARGUMENT",
                            ValidationIssueCategory.ARGUMENT,
                            error_field,
                        )
                    )

        blocking = [
            issue
            for issue in issues
            if issue.code
            not in {
                "MISSING_ARGUMENT",
                "AMBIGUOUS_ARGUMENT",
                "LOW_CONFIDENCE",
                "ROUTING_AMBIGUOUS",
            }
        ]
        requires_confirmation = is_write and not clarification and not blocking
        valid = not blocking and not clarification
        return self._build_result(
            valid=valid,
            can_execute=valid and not requires_confirmation,
            requires_clarification=clarification and not blocking,
            requires_confirmation=requires_confirmation,
            normalized_arguments=normalized,
            issues=issues,
            missing_arguments=resolution.missing_arguments,
            ambiguous_arguments=resolution.ambiguous_arguments,
        )

    def _threshold(self, risk: RiskLevel) -> float:
        if risk in {RiskLevel.WRITE, RiskLevel.HIGH_RISK_WRITE}:
            return self._write_threshold
        if risk is RiskLevel.SENSITIVE_READ:
            return self._sensitive_threshold
        return self._read_threshold

    @classmethod
    def _failure(
        cls,
        code: str,
        category: ValidationIssueCategory,
        field: str | None = None,
    ) -> ToolValidationResult:
        return cls._build_result(
            valid=False,
            can_execute=False,
            requires_clarification=False,
            requires_confirmation=False,
            normalized_arguments={},
            issues=[cls._issue(code, category, field)],
            missing_arguments=[],
            ambiguous_arguments=[],
        )

    @staticmethod
    def _issue(
        code: str,
        category: ValidationIssueCategory,
        field: str | None = None,
    ) -> ValidationIssue:
        return ValidationIssue(
            code=code,
            category=category,
            field=field,
            message=code,
        )

    @staticmethod
    def _build_result(
        *,
        valid: bool,
        can_execute: bool,
        requires_clarification: bool,
        requires_confirmation: bool,
        normalized_arguments: dict[str, Any],
        issues: list[ValidationIssue],
        missing_arguments: list[str],
        ambiguous_arguments: list[str],
    ) -> ToolValidationResult:
        routing = [
            issue
            for issue in issues
            if issue.category is ValidationIssueCategory.ROUTING
        ]
        arguments = [
            issue
            for issue in issues
            if issue.category is ValidationIssueCategory.ARGUMENT
        ]
        security = [
            issue
            for issue in issues
            if issue.category is ValidationIssueCategory.SECURITY
        ]
        return ToolValidationResult(
            valid=valid,
            can_execute=can_execute,
            requires_clarification=requires_clarification,
            requires_confirmation=requires_confirmation,
            normalized_arguments=normalized_arguments,
            errors=issues,
            routing=RoutingValidationResult(valid=not routing, issues=routing),
            arguments=ArgumentValidationResult(
                valid=not arguments,
                requires_clarification=requires_clarification,
                normalized_arguments=normalized_arguments,
                missing_arguments=missing_arguments,
                ambiguous_arguments=ambiguous_arguments,
                issues=arguments,
            ),
            security=SecurityValidationResult(
                valid=not security,
                issues=security,
            ),
        )
