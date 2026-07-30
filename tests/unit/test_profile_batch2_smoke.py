from __future__ import annotations

import json
from collections.abc import Awaitable, Callable

import httpx
import pytest

from app.answers.sanitizer import ToolResultSanitizer
from app.context.actor import ActorContext
from app.context.entities import ResolvedSubject
from app.context.entity_resolver import EntityResolver
from app.context.subject_resolver import (
    SubjectResolutionStatus,
    SubjectResolver,
)
from app.integrations.odoo.client import OdooClient
from app.routing.intent_refiner import refine_read_intent
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
from app.tools.definitions import TrustedExecutionContext
from app.tools.executor import ToolExecutor
from tests.conftest import build_settings

Handler = Callable[[httpx.Request], Awaitable[httpx.Response]]


def _seed() -> QueryClassification:
    return QueryClassification(
        route=QueryRoute.DATA_QUERY,
        domain=Domain.GENERAL,
        intent=Intent.PROFILE_SUMMARY,
        operation=Operation.READ,
        scope=SubjectScope.SELF,
        confidence=0.7,
    )


def _route(query: str) -> tuple[QueryClassification, list[str]]:
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


def test_1_self_ethnicity_routes_to_identity() -> None:
    classification, tools = _route("dân tộc của tôi")
    assert classification.intent is Intent.PROFILE_IDENTITY
    assert classification.scope is SubjectScope.SELF
    assert tools == ["profile_get_identity"]


def test_2_identity_issue_date_and_sanitizer_preserve_mask() -> None:
    classification, tools = _route("CCCD của tôi cấp ngày nào")
    assert classification.intent is Intent.PROFILE_IDENTITY
    assert tools == ["profile_get_identity"]
    sanitized = ToolResultSanitizer(
        max_items=20,
        max_chars=12000,
    ).sanitize(
        intent=classification.intent,
        tool_name=tools[0],
        data={
            "identity_number": "********8901",
            "identity_issue_date": "2020-01-02",
            "attachment": "binary-data",
        },
    )
    assert sanitized == {
        "identity_number": "********8901",
        "identity_issue_date": "2020-01-02",
    }


def test_3_current_address_routes_to_address_group() -> None:
    classification, tools = _route("nơi ở hiện tại của tôi")
    assert classification.intent is Intent.PROFILE_ADDRESS
    assert tools == ["profile_get_addresses"]


def test_4_recruitment_date_routes_to_recruitment_group() -> None:
    classification, tools = _route("tôi vào TCT từ ngày nào")
    assert classification.intent is Intent.PROFILE_RECRUITMENT
    assert tools == ["profile_get_recruitment"]


def test_5_training_history_routes_to_dedicated_tool() -> None:
    classification, tools = _route("lịch sử đào tạo của tôi")
    assert classification.intent is Intent.PROFILE_TRAINING_HISTORY
    assert tools == ["profile_get_training_history"]


def test_6_appointment_history_routes_to_dedicated_tool() -> None:
    classification, tools = _route("quá trình bổ nhiệm của tôi")
    assert classification.intent is Intent.PROFILE_APPOINTMENT_HISTORY
    assert tools == ["profile_get_appointment_history"]


class _Lookup:
    async def search_employees(
        self,
        *,
        name: str | None,
        code: str | None,
        actor: ActorContext,
    ) -> list[ResolvedSubject]:
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
async def test_7_named_transfer_resolves_subject_before_tool() -> None:
    query = "Lò Văn Định đã từng điều chuyển chưa"
    classification, tools = _route(query)
    assert classification.intent is Intent.PROFILE_TRANSFER_HISTORY
    assert classification.scope is SubjectScope.NAMED_EMPLOYEE
    assert tools == ["employee_get_transfer_history"]
    mention = EntityResolver().extract_subject(query)
    resolution = await SubjectResolver(_Lookup()).resolve(
        mention,
        ActorContext(odoo_user_id=7, linked_employee_id=None),
    )
    assert resolution.status is SubjectResolutionStatus.RESOLVED
    assert resolution.subject is not None
    assert resolution.subject.employee_id == 91


@pytest.mark.asyncio
async def test_8_named_identity_odoo_access_denied_is_preserved() -> None:
    query = "Dân tộc của Lò Văn Định"
    classification, tools = _route(query)
    assert tools == ["employee_get_identity"]
    trusted = TrustedExecutionContext(
        odoo_user_id=7,
        employee_id=None,
        company_id=1,
        conversation_id="conv-batch2",
        request_id="req-batch2",
    )
    subject = ResolvedSubject(
        type=SubjectType.EMPLOYEE,
        employee_id=91,
        employee_name="Lò Văn Định",
        source="odoo_lookup",
    )
    policy = AuthorizationPolicyService(build_tool_registry()).authorize(
        AuthorizationRequest(
            tool_name=tools[0],
            intent=classification.intent or Intent.PROFILE_IDENTITY,
            operation=classification.operation,
            scope=classification.scope,
            trusted_context=trusted,
            resolved_subject=subject,
        ),
        allowed_tools=set(tools),
    )
    assert policy.allowed
    assert policy.reason_code == "POLICY_PRECHECK_PASSED"

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/employees/91/identity")
        return httpx.Response(
            403,
            content=json.dumps(
                {
                    "success": False,
                    "code": "ACCESS_DENIED",
                    "message": "Forbidden",
                    "data": None,
                    "meta": {
                        "request_id": "req-batch2",
                        "timestamp": "2026-07-30T00:00:00Z",
                    },
                }
            ).encode(),
        )

    client = OdooClient(
        build_settings(),
        transport=httpx.MockTransport(handler),
    )
    try:
        result = await ToolExecutor(
            build_tool_registry(),
            client,
        ).execute(
            tools[0],
            {"employee_id": 91},
            context=trusted,
        )
    finally:
        await client.close()
    assert result.success is False
    assert result.error_code == "ACCESS_DENIED"

