from __future__ import annotations

from secrets import token_urlsafe

from pydantic import ValidationError

from app.config import Settings
from app.routing.argument_resolver import ArgumentResolution
from app.routing.schemas import (
    QueryClassification,
    RouteType,
    ToolCandidateContext,
    ToolSelection,
    ToolValidationResult,
    ValidationIssue,
)
from app.tools.definitions import (
    RiskLevel,
)
from app.tools.definitions import (
    RouteType as ToolRouteType,
)
from app.tools.registry import ToolNotFoundError, ToolRegistry


class ToolSelectionValidator:
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
            return self._result(
                issues=[
                    ValidationIssue(
                        code="NO_TOOL_SELECTED",
                        message="Không có tool phù hợp.",
                    )
                ],
                clarification=False,
            )
        candidate = candidate_map.get(selection.selected_tool)
        if candidate is None:
            return self._result(
                issues=[
                    ValidationIssue(
                        code="TOOL_OUTSIDE_CANDIDATES",
                        field="selected_tool",
                        message="Tool không nằm trong candidate allowlist.",
                    )
                ],
                clarification=False,
            )
        try:
            tool = self._registry.get(selection.selected_tool)
        except ToolNotFoundError:
            return self._result(
                issues=[
                    ValidationIssue(
                        code="TOOL_NOT_REGISTERED",
                        field="selected_tool",
                        message="Tool không tồn tại trong registry.",
                    )
                ],
                clarification=False,
            )
        if not tool.enabled:
            issues.append(
                ValidationIssue(
                    code="TOOL_DISABLED",
                    field="selected_tool",
                    message="Tool đang bị vô hiệu hóa.",
                )
            )
        if tool.domain.value != classification.primary_domain.value:
            issues.append(
                ValidationIssue(
                    code="DOMAIN_MISMATCH",
                    field="selected_tool",
                    message="Domain của tool không khớp classification.",
                )
            )
        expected_transaction = (
            classification.route_type is RouteType.TRANSACTION
        )
        if expected_transaction != (tool.route_type is ToolRouteType.COMMAND):
            issues.append(
                ValidationIssue(
                    code="ROUTE_MISMATCH",
                    field="selected_tool",
                    message="Route của tool không khớp classification.",
                )
            )
        supported_scopes = {scope.value for scope in tool.supported_scopes}
        if classification.scope.value not in supported_scopes:
            issues.append(
                ValidationIssue(
                    code="SCOPE_NOT_SUPPORTED",
                    field="scope",
                    message="Tool không hỗ trợ scope được yêu cầu.",
                )
            )
        if candidate.score < self._min_score:
            issues.append(
                ValidationIssue(
                    code="CANDIDATE_SCORE_TOO_LOW",
                    field="score",
                    message="Candidate score dưới ngưỡng.",
                )
            )

        threshold = self._threshold(tool.risk_level)
        if selection.confidence < threshold:
            issues.append(
                ValidationIssue(
                    code="SELECTION_CONFIDENCE_TOO_LOW",
                    field="confidence",
                    message="Độ tin cậy chọn tool dưới ngưỡng.",
                )
            )
        scores = sorted(
            (item.score for item in candidates),
            reverse=True,
        )
        if (
            len(scores) > 1
            and scores[0] - scores[1] < self._min_margin
            and selection.confidence < min(1.0, threshold + 0.05)
        ):
            issues.append(
                ValidationIssue(
                    code="CANDIDATE_MARGIN_TOO_LOW",
                    field="score",
                    message="Các candidate đầu quá gần nhau.",
                )
            )
        for field in resolution.rejected_trusted_fields:
            issues.append(
                ValidationIssue(
                    code="TRUSTED_FIELD_REJECTED",
                    field=field,
                    message="Trusted context không được lấy từ LLM.",
                )
            )

        clarification = bool(
            resolution.missing_arguments
            or resolution.ambiguous_arguments
            or selection.requires_clarification
        )
        for field in resolution.missing_arguments:
            issues.append(
                ValidationIssue(
                    code="MISSING_REQUIRED_ARGUMENT",
                    field=field,
                    message="Thiếu argument bắt buộc.",
                )
            )
        for field in resolution.ambiguous_arguments:
            issues.append(
                ValidationIssue(
                    code="AMBIGUOUS_ARGUMENT",
                    field=field,
                    message="Argument chưa đủ rõ.",
                )
            )

        normalized = dict(resolution.arguments)
        is_write = tool.risk_level in {
            RiskLevel.WRITE,
            RiskLevel.HIGH_RISK_WRITE,
        }
        if is_write and not clarification:
            normalized.setdefault(
                "idempotency_key",
                f"chat-{token_urlsafe(18)}",
            )
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
                        ValidationIssue(
                            code="INVALID_ARGUMENT",
                            field=error_field,
                            message="Argument không đúng schema.",
                        )
                    )

        blocking = [
            issue
            for issue in issues
            if issue.code
            not in {"MISSING_REQUIRED_ARGUMENT", "AMBIGUOUS_ARGUMENT"}
        ]
        requires_confirmation = is_write and not clarification and not blocking
        valid = not blocking and not clarification
        return ToolValidationResult(
            valid=valid,
            can_execute=valid and not requires_confirmation,
            requires_clarification=clarification and not blocking,
            requires_confirmation=requires_confirmation,
            normalized_arguments=normalized,
            errors=issues,
        )

    def _threshold(self, risk: RiskLevel) -> float:
        if risk in {RiskLevel.WRITE, RiskLevel.HIGH_RISK_WRITE}:
            return self._write_threshold
        if risk is RiskLevel.SENSITIVE_READ:
            return self._sensitive_threshold
        return self._read_threshold

    @staticmethod
    def _result(
        *,
        issues: list[ValidationIssue],
        clarification: bool,
    ) -> ToolValidationResult:
        return ToolValidationResult(
            valid=False,
            can_execute=False,
            requires_clarification=clarification,
            requires_confirmation=False,
            errors=issues,
        )
