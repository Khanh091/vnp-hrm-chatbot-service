from __future__ import annotations

from collections.abc import AsyncIterator

import pytest

from app.answers.fallback import DeterministicAnswerFallback
from app.answers.schemas import FinalAnswerContext
from app.answers.service import FinalAnswerService
from app.context.actor import ActorContext
from app.context.dialog_manager import DialogTurnManager
from app.context.entities import ResolvedSubject, SubjectMention
from app.context.entity_memory import (
    ConversationEntityMemory,
    EntityMemoryService,
)
from app.context.entity_resolver import EntityResolver
from app.context.subject_resolver import (
    SubjectLookupProvider,
    SubjectResolutionStatus,
    SubjectResolver,
)
from app.orchestration.state import TurnType
from app.routing.intent_refiner import refine_read_intent
from app.routing.intent_tool_mapping import tool_names_for_intent
from app.routing.schemas import Domain, QueryClassification
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
from app.tools.definitions import (
    Domain as ToolDomain,
)
from app.tools.definitions import (
    HttpMethod,
    NoArguments,
    RiskLevel,
    RouteType,
    ToolDefinition,
    TrustedExecutionContext,
)
from app.tools.definitions import (
    Operation as ToolOperation,
)
from app.tools.definitions import (
    SubjectScope as ToolSubjectScope,
)
from app.tools.registry import ToolRegistry


def _classification() -> QueryClassification:
    return QueryClassification(
        route=QueryRoute.DATA_QUERY,
        domain=Domain.ATTENDANCE,
        intent=Intent.ATTENDANCE_DAILY,
        operation=Operation.READ,
        scope=SubjectScope.SELF,
        confidence=0.9,
    )


@pytest.mark.parametrize(
    ("query", "expected_intent"),
    [
        (
            "số lần quên chấm công của tôi",
            Intent.ATTENDANCE_MISSING_PUNCH_COUNT,
        ),
        (
            "số ngày làm việc trong tháng của tôi",
            Intent.ATTENDANCE_ACTUAL_WORK_DAYS,
        ),
    ],
)
def test_read_routing_isolation(
    query: str,
    expected_intent: Intent,
) -> None:
    refined = refine_read_intent(query, _classification())

    assert refined.operation is Operation.READ
    assert refined.intent is expected_intent
    assert tool_names_for_intent(expected_intent) == (
        "attendance_get_monthly_summary",
    )
    matches = build_tool_registry().find_tools(
        intent=refined.intent,
        domain=refined.domain.value if refined.domain else None,
        route=refined.route,
        operation=refined.operation,
        scope=refined.scope,
    )
    assert [tool.name for tool in matches] == [
        "attendance_get_monthly_summary"
    ]
    assert all(tool.query_operation is Operation.READ for tool in matches)


def test_sticky_workflow_detects_new_intents() -> None:
    manager = DialogTurnManager()

    assert manager.detect(
        message="lịch sử chấm công",
        structured_clarification=None,
        expected_field="date_from",
    ) is TurnType.NEW_QUERY_OVERRIDE
    assert manager.detect(
        message="số ngày phép còn lại",
        structured_clarification=None,
        expected_field="date_from",
    ) is TurnType.NEW_QUERY_OVERRIDE


def test_leave_reference_memory_resolves_latest() -> None:
    service = EntityMemoryService()
    memory = service.capture(
        tool_name="leave_get_history",
        data={
            "records": [
                {
                    "id": 123,
                    "code": "LEAVE-00123",
                    "date_from": "2026-08-01",
                    "date_to": "2026-08-03",
                    "state": "confirm",
                },
                {"id": 100, "code": "LEAVE-00100"},
            ]
        },
        memory=ConversationEntityMemory(),
    )

    resolved = service.resolve_leave_request(
        SubjectMention(type=SubjectType.SELF, recency_reference="latest"),
        memory,
    )
    assert resolved is not None
    assert resolved.entity_id == 123
    assert resolved.label.startswith("LEAVE-00123")


class _LookupProvider(SubjectLookupProvider):
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
                employee_id=42,
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


def _directory_tool() -> ToolDefinition:
    return ToolDefinition(
        name="employee_get_employment",
        domain=ToolDomain.DIRECTORY,
        capability=Intent.DIRECTORY_EMPLOYEE_DEPARTMENT.value,
        operation=ToolOperation.GET,
        route_type=RouteType.QUERY,
        risk_level=RiskLevel.READ,
        description="Tra cứu đơn vị công tác của nhân viên theo lookup allowlist.",
        endpoint="/api/hrm-chatbot/v1/directory/employees/employment",
        http_method=HttpMethod.GET,
        argument_schema=NoArguments,
        examples=("a", "b", "c", "d", "e"),
        negative_examples=("x", "y", "z"),
        supported_scopes=(ToolSubjectScope.NAMED_EMPLOYEE,),
    )


@pytest.mark.asyncio
async def test_admin_without_employee_can_resolve_named_subject() -> None:
    actor = ActorContext(
        odoo_user_id=7,
        company_ids=(1,),
        group_codes=("hr.group_hr_user",),
        locale="vi_VN",
        timezone="Asia/Ho_Chi_Minh",
        linked_employee_id=None,
    )
    mention = EntityResolver().extract_subject(
        "Lò Văn Định ở cơ quan nào"
    )
    assert mention.employee_name == "Lò Văn Định"
    resolution = await SubjectResolver(_LookupProvider()).resolve(
        mention,
        actor,
    )
    assert resolution.status is SubjectResolutionStatus.RESOLVED
    assert resolution.subject is not None

    registry = ToolRegistry((_directory_tool(),))
    decision = AuthorizationPolicyService(registry).authorize(
        AuthorizationRequest(
            tool_name="employee_get_employment",
            intent=Intent.DIRECTORY_EMPLOYEE_DEPARTMENT,
            operation=Operation.READ,
            scope=SubjectScope.NAMED_EMPLOYEE,
            trusted_context=TrustedExecutionContext(
                odoo_user_id=actor.odoo_user_id,
                company_ids=actor.company_ids,
                group_codes=actor.group_codes,
                employee_id=None,
                request_id="req-admin",
            ),
            resolved_subject=resolution.subject,
        ),
        allowed_tools={"employee_get_employment"},
    )
    assert decision.allowed


def test_self_without_employee_is_typed_denial() -> None:
    registry = build_tool_registry()
    decision = AuthorizationPolicyService(registry).authorize(
        AuthorizationRequest(
            tool_name="profile_get_employment",
            intent=Intent.PROFILE_DEPARTMENT,
            operation=Operation.READ,
            scope=SubjectScope.SELF,
            trusted_context=TrustedExecutionContext(
                odoo_user_id=7,
                employee_id=None,
                request_id="req-self",
            ),
            resolved_subject=None,
        ),
        allowed_tools={"profile_get_employment"},
    )
    assert not decision.allowed
    assert decision.reason_code == "SELF_EMPLOYEE_NOT_LINKED"


class _FocusedAnswerClient:
    def __init__(self) -> None:
        self.user_prompt = ""

    async def stream_text(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int,
        temperature: float,
        operation: str = "text_stream",
        request_id: str | None = None,
    ) -> AsyncIterator[str]:
        self.user_prompt = user_prompt
        yield "Lò Văn Định hiện thuộc "
        yield "BƯU ĐIỆN KHU VỰC BẮC YÊN."


@pytest.mark.asyncio
async def test_final_answer_focuses_on_original_question() -> None:
    client = _FocusedAnswerClient()
    service = FinalAnswerService(
        client,
        DeterministicAnswerFallback(),
        temperature=0.1,
        max_tokens=100,
    )
    context = FinalAnswerContext(
        original_query="Lò Văn Định ở cơ quan nào?",
        route=QueryRoute.DATA_QUERY,
        intent=Intent.DIRECTORY_EMPLOYEE_DEPARTMENT,
        operation=Operation.READ,
        tool_name="employee_get_employment",
        data={
            "employee": "Lò Văn Định",
            "department": {"name": "BƯU ĐIỆN KHU VỰC BẮC YÊN"},
            "job_title": {"name": "Bán hàng"},
        },
        locale="vi_VN",
        timezone="Asia/Ho_Chi_Minh",
    )

    answer = "".join(
        [
            chunk
            async for chunk in service.stream_answer(
                context,
                request_id="req-answer",
            )
        ]
    )
    assert answer == (
        "Lò Văn Định hiện thuộc BƯU ĐIỆN KHU VỰC BẮC YÊN."
    )
    assert "Lò Văn Định ở cơ quan nào?" in client.user_prompt
