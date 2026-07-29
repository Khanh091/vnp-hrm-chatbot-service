import pytest

from app.common.error_messages import category_for_error, public_error_message
from app.context.entities import ResolvedSubject
from app.routing.schemas import ValidationIssueCategory
from app.routing.taxonomy import SubjectScope
from app.security.authorization import (
    AuthorizationPolicyService,
    AuthorizationRequest,
)
from app.tools import build_tool_registry
from app.tools.definitions import SubjectScope as ToolSubjectScope
from app.tools.definitions import TrustedExecutionContext
from app.tools.registry import ToolRegistry


def trusted() -> TrustedExecutionContext:
    return TrustedExecutionContext(
        odoo_user_id=42,
        employee_id=7,
        company_id=1,
        request_id="request-1",
    )


@pytest.mark.parametrize(
    "tool_name",
    [
        "profile_get_employment",
        "profile_get_education",
        "leave_get_balance",
    ],
)
def test_self_read_passes_fastapi_policy(tool_name: str) -> None:
    registry = build_tool_registry()
    tool = registry.get(tool_name)
    service = AuthorizationPolicyService(registry)
    context = trusted()

    decision = service.authorize(
        AuthorizationRequest(
            tool_name=tool.name,
            intent=tool.intent,
            operation=tool.query_operation,
            scope=SubjectScope.SELF,
            trusted_context=context,
            resolved_subject=ResolvedSubject(
                scope=SubjectScope.SELF,
                employee_id=context.employee_id,
                source="trusted_context",
            ),
        ),
        allowed_tools={tool.name},
    )

    assert decision.allowed is True
    assert decision.source == "fastapi_policy"


def test_named_employee_can_continue_to_odoo_when_tool_supports_it() -> None:
    original = build_tool_registry().get("profile_get_contact")
    named_tool = original.model_copy(
        update={
            "supported_scopes": (
                ToolSubjectScope.SELF,
                ToolSubjectScope.NAMED_EMPLOYEE,
            )
        }
    )
    registry = ToolRegistry([named_tool])
    service = AuthorizationPolicyService(registry)

    decision = service.authorize(
        AuthorizationRequest(
            tool_name=named_tool.name,
            intent=named_tool.intent,
            operation=named_tool.query_operation,
            scope=SubjectScope.NAMED_EMPLOYEE,
            trusted_context=trusted(),
            resolved_subject=ResolvedSubject(
                scope=SubjectScope.NAMED_EMPLOYEE,
                employee_id=88,
                employee_name="Nguyễn Văn A",
                source="odoo_lookup",
            ),
        )
    )

    assert decision.allowed is True


def test_named_employee_is_not_guessed_from_text() -> None:
    registry = build_tool_registry()
    tool = registry.get("profile_get_contact")
    decision = AuthorizationPolicyService(registry).authorize(
        AuthorizationRequest(
            tool_name=tool.name,
            intent=tool.intent,
            operation=tool.query_operation,
            scope=SubjectScope.NAMED_EMPLOYEE,
            trusted_context=trusted(),
            resolved_subject=None,
        )
    )

    assert decision.allowed is False
    assert decision.reason_code == "SCOPE_NOT_ALLOWED"


def test_security_guard_rejects_trusted_and_arbitrary_execution_fields() -> None:
    service = AuthorizationPolicyService(build_tool_registry())

    result = service.validate_security(
        {"odoo_user_id": 99, "model": "hr.employee"}
    )

    assert result.valid is False
    assert {issue.code for issue in result.issues} == {
        "TRUSTED_FIELD_INJECTION",
        "SECURITY_REJECTED",
    }


@pytest.mark.parametrize(
    ("code", "category", "message"),
    [
        (
            "ROUTING_AMBIGUOUS",
            ValidationIssueCategory.ROUTING,
            "Tôi chưa xác định chính xác thông tin bạn muốn tra cứu.",
        ),
        (
            "INVALID_ARGUMENT",
            ValidationIssueCategory.ARGUMENT,
            "Thông tin bạn cung cấp chưa hợp lệ.",
        ),
        (
            "ACCESS_DENIED",
            ValidationIssueCategory.AUTHORIZATION,
            "Bạn không có quyền truy cập thông tin này.",
        ),
        (
            "SECURITY_REJECTED",
            ValidationIssueCategory.SECURITY,
            "Yêu cầu bị từ chối vì lý do an toàn.",
        ),
        (
            "INVALID_LEAVE_DATE_RANGE",
            ValidationIssueCategory.BUSINESS,
            (
                "Khoảng ngày nghỉ không có thời gian làm việc hợp lệ. "
                "Vui lòng kiểm tra lịch làm việc hoặc chọn khoảng ngày khác."
            ),
        ),
    ],
)
def test_error_categories_have_distinct_public_messages(
    code: str,
    category: ValidationIssueCategory,
    message: str,
) -> None:
    assert category_for_error(code) is category
    assert public_error_message(code, category) == message
