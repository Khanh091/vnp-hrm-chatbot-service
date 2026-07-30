from __future__ import annotations

import json

import httpx
import pytest

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
from app.tools.definitions import RiskLevel, TrustedExecutionContext
from app.tools.executor import ToolExecutor
from tests.conftest import build_settings


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
    assert all(tool.risk_level is RiskLevel.SENSITIVE_READ for tool in tools)
    return classification, [tool.name for tool in tools]


def test_1_self_rewards_routes_to_rewards_group() -> None:
    classification, tools = _route("tôi đã được khen thưởng gì")
    assert classification.intent is Intent.PROFILE_REWARDS
    assert tools == ["profile_get_rewards"]


def test_2_self_discipline_routes_to_disciplines_group() -> None:
    classification, tools = _route("lịch sử kỷ luật của tôi")
    assert classification.intent is Intent.PROFILE_DISCIPLINES
    assert tools == ["profile_get_disciplines"]


def test_3_latest_evaluation_routes_to_evaluations_group() -> None:
    classification, tools = _route("kết quả đánh giá gần nhất")
    assert classification.intent is Intent.PROFILE_EVALUATIONS
    assert classification.scope is SubjectScope.SELF
    assert tools == ["profile_get_evaluations"]


def test_4_party_membership_routes_only_to_party_union() -> None:
    classification, tools = _route("tôi có phải Đảng viên không")
    assert classification.intent is Intent.PROFILE_PARTY_UNION
    assert tools == ["profile_get_party_union"]


def test_5_union_join_date_routes_only_to_party_union() -> None:
    classification, tools = _route("ngày vào Đoàn của tôi")
    assert classification.intent is Intent.PROFILE_PARTY_UNION
    assert tools == ["profile_get_party_union"]


def test_6_preferences_routes_to_preferences_group() -> None:
    classification, tools = _route("sở thích của tôi")
    assert classification.intent is Intent.PROFILE_PREFERENCES
    assert tools == ["profile_get_preferences"]


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
async def test_7_named_discipline_resolves_subject_before_tool() -> None:
    query = "kỷ luật của Lò Văn Định"
    classification, tools = _route(query)
    assert classification.intent is Intent.PROFILE_DISCIPLINES
    assert classification.scope is SubjectScope.NAMED_EMPLOYEE
    assert tools == ["employee_get_disciplines"]
    mention = EntityResolver().extract_subject(query)
    resolution = await SubjectResolver(_Lookup()).resolve(
        mention,
        ActorContext(odoo_user_id=7, linked_employee_id=None),
    )
    assert resolution.status is SubjectResolutionStatus.RESOLVED
    assert resolution.subject is not None
    assert resolution.subject.employee_id == 91


@pytest.mark.asyncio
async def test_8_named_sensitive_access_denied_is_preserved() -> None:
    query = "sở thích của Lò Văn Định"
    classification, tools = _route(query)
    assert tools == ["employee_get_preferences"]
    trusted = TrustedExecutionContext(
        odoo_user_id=7,
        employee_id=None,
        company_id=1,
        conversation_id="conv-batch3",
        request_id="req-batch3",
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
            intent=classification.intent or Intent.PROFILE_PREFERENCES,
            operation=classification.operation,
            scope=classification.scope,
            trusted_context=trusted,
            resolved_subject=subject,
        ),
        allowed_tools=set(tools),
    )
    assert policy.allowed

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/employees/91/preferences")
        return httpx.Response(
            403,
            content=json.dumps(
                {
                    "success": False,
                    "code": "ACCESS_DENIED",
                    "message": "Forbidden",
                    "data": None,
                    "meta": {
                        "request_id": "req-batch3",
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

