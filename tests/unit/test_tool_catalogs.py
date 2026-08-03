import pytest

from app.tools.catalogs import ALL_TOOLS
from app.tools.definitions import Domain, RiskLevel, RouteType
from app.tools.policies import validate_tool_definition

ODOO_CONTROLLER_ENDPOINTS = {
    "/api/hrm-chatbot/v1/profile/current/summary",
    "/api/hrm-chatbot/v1/profile/current/employment",
    "/api/hrm-chatbot/v1/profile/current/contact",
    "/api/hrm-chatbot/v1/profile/current/history",
    "/api/hrm-chatbot/v1/profile/current/education",
    "/api/hrm-chatbot/v1/profile/current/certificates",
    "/api/hrm-chatbot/v1/profile/current/skills",
    "/api/hrm-chatbot/v1/profile/current/insurance",
    "/api/hrm-chatbot/v1/profile/current/tax",
    "/api/hrm-chatbot/v1/profile/current/bank-accounts",
    "/api/hrm-chatbot/v1/profile/current/contracts",
    "/api/hrm-chatbot/v1/attendance/current/daily",
    "/api/hrm-chatbot/v1/attendance/current/monthly-summary",
    "/api/hrm-chatbot/v1/attendance/current/history",
    "/api/hrm-chatbot/v1/attendance/current/late-summary",
    "/api/hrm-chatbot/v1/attendance/current/missing-punch-summary",
    "/api/hrm-chatbot/v1/attendance/current/missing-work-context",
    "/api/hrm-chatbot/v1/leave/types",
    "/api/hrm-chatbot/v1/leave/current/balance",
    "/api/hrm-chatbot/v1/leave/current/used",
    "/api/hrm-chatbot/v1/leave/current/history",
    "/api/hrm-chatbot/v1/leave/current/calendar",
    "/api/hrm-chatbot/v1/leave/current/request-status",
    "/api/hrm-chatbot/v1/leave/current/eligibility",
    "/api/hrm-chatbot/v1/leave/requests",
    "/api/hrm-chatbot/v1/leave/requests/actionable",
    "/api/hrm-chatbot/v1/leave/requests/{request_id}",
    "/api/hrm-chatbot/v1/leave/requests/{request_id}/cancel",
    "/api/v1/hrm/employees/search-by-certificate",
    "/api/v1/hrm/contracts/expiring",
    "/api/v1/hrm/employees/search",
    "/api/v1/hrm/departments/{department_id}/employees",
    "/api/v1/hrm/departments",
    "/api/v1/hrm/employees/{employee_id}/basic",
    "/api/v1/hrm/employees/{employee_id}/employment",
    "/api/v1/hrm/employees/{employee_id}/contact",
    "/api/v1/hrm/employees/{employee_id}/education",
    "/api/v1/hrm/employees/{employee_id}/certificates",
    "/api/v1/hrm/employees/{employee_id}/work-history",
    "/api/v1/hrm/employees/{employee_id}/contracts",
    "/api/v1/hrm/employees/{employee_id}/bank-tax",
    "/api/v1/hrm/employees/{employee_id}/insurance",
    "/api/v1/hrm/profile/current/identity",
    "/api/v1/hrm/profile/current/addresses",
    "/api/v1/hrm/profile/current/recruitment",
    "/api/v1/hrm/profile/current/training-history",
    "/api/v1/hrm/profile/current/appointment-history",
    "/api/v1/hrm/profile/current/transfer-history",
    "/api/v1/hrm/employees/{employee_id}/identity",
    "/api/v1/hrm/employees/{employee_id}/addresses",
    "/api/v1/hrm/employees/{employee_id}/recruitment",
    "/api/v1/hrm/employees/{employee_id}/training-history",
    "/api/v1/hrm/employees/{employee_id}/appointment-history",
    "/api/v1/hrm/employees/{employee_id}/transfer-history",
    "/api/v1/hrm/profile/current/family-relations",
    "/api/v1/hrm/profile/current/personal-background",
    "/api/v1/hrm/profile/current/family-economy",
    "/api/v1/hrm/profile/current/health",
    "/api/v1/hrm/profile/current/rewards",
    "/api/v1/hrm/profile/current/disciplines",
    "/api/v1/hrm/profile/current/evaluations",
    "/api/v1/hrm/profile/current/party-union",
    "/api/v1/hrm/profile/current/preferences",
    "/api/v1/hrm/employees/{employee_id}/family-relations",
    "/api/v1/hrm/employees/{employee_id}/personal-background",
    "/api/v1/hrm/employees/{employee_id}/family-economy",
    "/api/v1/hrm/employees/{employee_id}/health",
    "/api/v1/hrm/employees/{employee_id}/rewards",
    "/api/v1/hrm/employees/{employee_id}/disciplines",
    "/api/v1/hrm/employees/{employee_id}/evaluations",
    "/api/v1/hrm/employees/{employee_id}/party-union",
    "/api/v1/hrm/employees/{employee_id}/preferences",
}


@pytest.mark.parametrize("tool", ALL_TOOLS, ids=lambda tool: tool.name)
def test_every_catalog_tool_has_valid_distinct_metadata(tool: object) -> None:
    validate_tool_definition(tool)  # type: ignore[arg-type]
    assert len(tool.examples) >= 5  # type: ignore[attr-defined]
    assert len(tool.negative_examples) >= 3  # type: ignore[attr-defined]
    assert set(tool.examples).isdisjoint(tool.negative_examples)  # type: ignore[attr-defined]


def test_catalog_contains_only_real_odoo_controller_endpoints() -> None:
    assert {tool.endpoint for tool in ALL_TOOLS} == ODOO_CONTROLLER_ENDPOINTS


def test_catalog_domain_counts_are_expected() -> None:
    assert sum(tool.domain is Domain.PROFILE for tool in ALL_TOOLS) == 48
    assert sum(tool.domain is Domain.ATTENDANCE for tool in ALL_TOOLS) == 6
    assert sum(tool.domain is Domain.LEAVE for tool in ALL_TOOLS) == 12
    assert sum(tool.domain is Domain.DIRECTORY for tool in ALL_TOOLS) == 7
    assert sum(tool.domain is Domain.REPORTING for tool in ALL_TOOLS) == 1


def test_leave_commands_require_confirmation_and_write_risk() -> None:
    commands = [
        tool
        for tool in ALL_TOOLS
        if tool.domain is Domain.LEAVE and tool.route_type is RouteType.COMMAND
    ]

    assert len(commands) == 3
    assert all(tool.risk_level is RiskLevel.WRITE for tool in commands)
    assert all(tool.requires_confirmation for tool in commands)
