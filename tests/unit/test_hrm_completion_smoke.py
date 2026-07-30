from __future__ import annotations

from datetime import date

import pytest

from app.context.actor import ActorContext
from app.context.dialog_manager import DialogTurnManager
from app.context.entities import ResolvedSubject
from app.context.entity_memory import (
    ConversationEntityMemory,
    EntityMemoryService,
)
from app.context.entity_resolver import EntityResolver
from app.context.subject_resolver import (
    SubjectResolutionStatus,
    SubjectResolver,
)
from app.orchestration.state import TurnType
from app.routing.argument_resolver import ArgumentResolver
from app.routing.intent_refiner import refine_read_intent
from app.routing.schemas import Domain, QueryClassification, ToolSelection
from app.routing.taxonomy import (
    Intent,
    Operation,
    QueryRoute,
    SubjectScope,
    SubjectType,
)
from app.security.authorization import (
    AuthorizationPolicyService,
    AuthorizationRequest,
)
from app.tools import build_tool_registry
from app.tools.definitions import TrustedExecutionContext


def _seed() -> QueryClassification:
    return QueryClassification(
        route=QueryRoute.DATA_QUERY,
        domain=Domain.GENERAL,
        intent=Intent.PROFILE_SUMMARY,
        operation=Operation.READ,
        scope=SubjectScope.SELF,
        confidence=0.7,
    )


def _direct_tools(query: str) -> tuple[QueryClassification, list[str]]:
    classification = refine_read_intent(query, _seed())
    tools = build_tool_registry().find_tools(
        intent=classification.intent,
        domain=classification.domain.value if classification.domain else None,
        route=classification.route,
        operation=classification.operation,
        scope=classification.scope,
    )
    assert all(tool.query_operation is Operation.READ for tool in tools)
    return classification, [tool.name for tool in tools]


def _selection(tool_name: str, scope: SubjectScope) -> ToolSelection:
    return ToolSelection(
        selected_tool=tool_name,
        confidence=1,
        scope=scope,
        extracted_arguments={},
    )


def test_1_missing_punch_is_direct_monthly_read() -> None:
    classification, tools = _direct_tools(
        "số lần quên chấm công của tôi"
    )
    assert classification.intent is Intent.ATTENDANCE_MISSING_PUNCH_COUNT
    assert tools == ["attendance_get_monthly_summary"]
    assert "leave_create_request" not in tools


def test_2_actual_work_days_is_direct_monthly_read() -> None:
    classification, tools = _direct_tools(
        "số ngày làm việc trong tháng của tôi"
    )
    assert classification.intent is Intent.ATTENDANCE_ACTUAL_WORK_DAYS
    assert tools == ["attendance_get_monthly_summary"]
    assert "leave_create_request" not in tools


def test_3_leave_slot_is_overridden_by_attendance_history() -> None:
    message = "lịch sử chấm công"
    turn = DialogTurnManager().detect(
        message=message,
        structured_clarification=None,
        expected_field="date_from",
    )
    assert turn is TurnType.NEW_QUERY_OVERRIDE
    classification, tools = _direct_tools(message)
    assert classification.intent is Intent.ATTENDANCE_HISTORY
    assert tools == ["attendance_get_history"]


def test_4_leave_latest_reference_uses_newest_saved_request() -> None:
    classification, tools = _direct_tools(
        "trạng thái đơn nghỉ phép của tôi"
    )
    assert classification.intent is Intent.LEAVE_REQUEST_STATUS
    assert set(tools) == {"leave_get_history", "leave_get_request_status"}

    service = EntityMemoryService()
    memory = service.capture(
        tool_name="leave_get_history",
        data={
            "records": [
                {
                    "id": 1,
                    "code": "LEAVE-00001",
                    "date_from": "2026-07-01",
                    "date_to": "2026-07-02",
                    "state": "approve",
                },
                {
                    "id": 2,
                    "code": "LEAVE-00002",
                    "date_from": "2026-07-29",
                    "date_to": "2026-07-30",
                    "state": "wait_approve",
                },
            ]
        },
        memory=ConversationEntityMemory(),
    )
    mention = EntityResolver().extract_subject("đơn gần nhất")
    resolved = service.resolve_leave_request(mention, memory)
    assert resolved is not None
    assert resolved.entity_id == 2
    assert "Chờ duyệt" in resolved.label


class _SubjectLookup:
    async def search_employees(
        self,
        *,
        name: str | None,
        code: str | None,
        actor: ActorContext,
    ) -> list[ResolvedSubject]:
        assert actor.linked_employee_id is None
        return [
            ResolvedSubject(
                type=SubjectType.EMPLOYEE,
                employee_id=91,
                employee_name=name,
                employee_code=code,
            )
        ]

    async def search_departments(
        self,
        *,
        name: str,
        actor: ActorContext,
    ) -> list[ResolvedSubject]:
        return []


@pytest.mark.asyncio
async def test_5_named_employee_resolves_without_linked_self_employee() -> None:
    classification, tools = _direct_tools("Lò Văn Định ở cơ quan nào")
    assert classification.intent is Intent.DIRECTORY_EMPLOYEE_DEPARTMENT
    assert tools == ["employee_get_employment"]
    mention = EntityResolver().extract_subject("Lò Văn Định ở cơ quan nào")
    result = await SubjectResolver(_SubjectLookup()).resolve(
        mention,
        ActorContext(
            odoo_user_id=7,
            linked_employee_id=None,
            capabilities=("directory.employee.read",),
        ),
    )
    assert result.status is SubjectResolutionStatus.RESOLVED
    assert result.subject is not None
    assert result.subject.employee_id == 91


def test_6_certificate_search_direct_maps_and_extracts_aws() -> None:
    classification, tools = _direct_tools("nhân viên nào có chứng chỉ AWS")
    assert classification.intent is Intent.DIRECTORY_EMPLOYEE_BY_CERTIFICATE
    assert tools == ["employee_find_by_certificate"]
    tool = build_tool_registry().get(tools[0])
    selection = _selection(tool.name, SubjectScope.COMPANY).model_copy(
        update={"extracted_arguments": {"department_id": 999}}
    )
    resolution = ArgumentResolver().resolve(
        selection,
        tool,
        query="nhân viên nào có chứng chỉ AWS",
        current_date=date(2026, 7, 30),
        timezone="Asia/Ho_Chi_Minh",
        conversation_arguments={"department_id": 5},
    )
    assert resolution.arguments["certificate_query"] == "AWS"
    assert resolution.arguments["department_id"] == 5
    assert resolution.rejected_trusted_fields == ["department_id"]


def test_7_contract_report_direct_maps_and_extracts_window() -> None:
    query = "liệt kê hợp đồng hết hạn trong 30 ngày tới"
    classification, tools = _direct_tools(query)
    assert classification.intent is Intent.REPORT_CONTRACTS_EXPIRING
    assert tools == ["contract_list_expiring"]
    tool = build_tool_registry().get(tools[0])
    resolution = ArgumentResolver().resolve(
        _selection(tool.name, SubjectScope.COMPANY),
        tool,
        query=query,
        current_date=date(2026, 7, 30),
        timezone="Asia/Ho_Chi_Minh",
    )
    assert resolution.arguments["within_days"] == 30
    tool.argument_schema.model_validate(resolution.arguments)


def test_8_admin_without_employee_passes_named_and_report_precheck() -> None:
    registry = build_tool_registry()
    policy = AuthorizationPolicyService(registry)
    trusted = TrustedExecutionContext(
        odoo_user_id=7,
        employee_id=None,
        company_id=1,
        company_ids=(1,),
        group_codes=("hr.group_hr_user",),
        capabilities=(
            "directory.employee_by_certificate",
            "report.contracts.expiring",
        ),
        conversation_id="conv-admin",
        request_id="req-admin",
    )
    named = policy.authorize(
        AuthorizationRequest(
            tool_name="employee_get_employment",
            intent=Intent.DIRECTORY_EMPLOYEE_DEPARTMENT,
            operation=Operation.READ,
            scope=SubjectScope.NAMED_EMPLOYEE,
            trusted_context=trusted,
            resolved_subject=ResolvedSubject(
                type=SubjectType.EMPLOYEE,
                employee_id=91,
                employee_name="Lò Văn Định",
                source="odoo_lookup",
            ),
        ),
        allowed_tools={"employee_get_employment"},
    )
    report = policy.authorize(
        AuthorizationRequest(
            tool_name="contract_list_expiring",
            intent=Intent.REPORT_CONTRACTS_EXPIRING,
            operation=Operation.READ,
            scope=SubjectScope.COMPANY,
            trusted_context=trusted,
        ),
        allowed_tools={"contract_list_expiring"},
    )
    assert named.allowed and named.reason_code == "POLICY_PRECHECK_PASSED"
    assert report.allowed and report.reason_code == "POLICY_PRECHECK_PASSED"
