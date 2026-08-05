from __future__ import annotations

import pytest

from app.context.actor import ActorContext
from app.context.entities import ResolvedSubject, SubjectMention
from app.context.entity_resolver import EntityResolver
from app.context.subject_resolver import (
    SubjectLookupProvider,
    SubjectResolutionStatus,
    SubjectResolver,
)
from app.orchestration.nodes.execute_read_tool import (
    build_department_membership_result,
)
from app.routing.capabilities import CapabilityResolver, ToolResolver
from app.routing.intent_refiner import direct_classify_from_exclusive_hints
from app.routing.query_normalizer import QueryNormalizer
from app.routing.rules import infer_rule_hints
from app.routing.taxonomy import Intent, SubjectScope, SubjectType
from app.tools import build_tool_registry
from app.workflows.clarification_policy import clarification_question


class DirectoryLookupStub(SubjectLookupProvider):
    def __init__(
        self,
        *,
        departments: list[ResolvedSubject] | None = None,
        employees: list[ResolvedSubject] | None = None,
    ) -> None:
        self.departments = departments or []
        self.employees = employees or []
        self.department_queries: list[str] = []
        self.employee_queries: list[tuple[str | None, str | None]] = []

    async def search_employees(
        self,
        *,
        name: str | None,
        code: str | None,
        actor: ActorContext,
    ) -> list[ResolvedSubject]:
        del actor
        self.employee_queries.append((name, code))
        return self.employees

    async def search_departments(
        self,
        *,
        name: str,
        actor: ActorContext,
    ) -> list[ResolvedSubject]:
        del actor
        self.department_queries.append(name)
        return self.departments


def _actor() -> ActorContext:
    return ActorContext(
        odoo_user_id=7,
        linked_employee_id=10,
        department_id=4,
        company_ids=(1,),
    )


def _direct(query: str):
    normalized = QueryNormalizer().normalize(query)
    return direct_classify_from_exclusive_hints(
        normalized,
        infer_rule_hints(normalized),
    )


def _tool_names(intent: Intent, subject_type: SubjectType) -> list[str]:
    registry = build_tool_registry()
    capabilities = CapabilityResolver().resolve(
        intent=intent,
        subject_type=subject_type,
    )
    return [
        tool.name
        for capability in capabilities
        for tool in ToolResolver(registry).resolve(
            capability=capability,
            subject_type=subject_type,
        )
    ]


def test_1_department_list_needs_no_department_id() -> None:
    classification = _direct("danh sách phòng ban")

    assert classification is not None
    assert classification.intent is Intent.DIRECTORY_DEPARTMENTS
    assert classification.scope is SubjectScope.COMPANY
    assert _tool_names(
        classification.intent,
        SubjectType.COMPANY,
    ) == ["department_list"]
    tool = build_tool_registry().get("department_list")
    assert "department_id" not in tool.argument_schema.model_fields


@pytest.mark.asyncio
async def test_2_actor_department_is_resolved_without_lookup() -> None:
    provider = DirectoryLookupStub()
    mention = EntityResolver().extract_subject(
        "nhân viên phòng ban của tôi"
    )
    resolution = await SubjectResolver(provider).resolve(mention, _actor())

    assert mention.use_actor_department
    assert resolution.status is SubjectResolutionStatus.RESOLVED
    assert resolution.subject is not None
    assert resolution.subject.department_id == 4
    assert resolution.subject.source == "trusted_context"
    assert provider.department_queries == []
    assert clarification_question("department_id") == (
        "Bạn muốn xem phòng ban nào?"
    )


@pytest.mark.asyncio
async def test_3_named_department_uses_bounded_lookup() -> None:
    provider = DirectoryLookupStub(
        departments=[
            ResolvedSubject(
                type=SubjectType.DEPARTMENT,
                department_id=31,
                department_name="BĐT Sơn La",
            )
        ]
    )
    mention = EntityResolver().extract_subject("nhân viên BĐT Sơn La")
    resolution = await SubjectResolver(provider).resolve(mention, _actor())

    assert mention.department_name == "BĐT Sơn La"
    assert provider.department_queries == ["BĐT Sơn La"]
    assert resolution.status is SubjectResolutionStatus.RESOLVED
    assert resolution.subject is not None
    assert resolution.subject.department_id == 31
    assert _tool_names(
        Intent.DIRECTORY_DEPARTMENT_EMPLOYEES,
        SubjectType.DEPARTMENT,
    ) == ["department_list_employees"]


@pytest.mark.asyncio
async def test_4_membership_resolves_employee_and_compares_ids() -> None:
    provider = DirectoryLookupStub(
        employees=[
            ResolvedSubject(
                type=SubjectType.EMPLOYEE,
                employee_id=22,
                employee_name="NGUYỄN ANH TUẤN",
            )
        ]
    )
    query = "NGUYỄN ANH TUẤN có ở phòng ban tôi không"
    mention = EntityResolver().extract_subject(query)
    resolution = await SubjectResolver(provider).resolve(mention, _actor())
    classification = _direct(query)

    assert classification is not None
    assert classification.intent is Intent.DIRECTORY_EMPLOYEE_IN_DEPARTMENT
    assert resolution.status is SubjectResolutionStatus.RESOLVED
    assert provider.employee_queries == [("NGUYỄN ANH TUẤN", None)]
    assert _tool_names(
        classification.intent,
        SubjectType.EMPLOYEE,
    ) == ["employee_check_department_membership"]
    compared = build_department_membership_result(
        {"department": {"id": 4, "name": "BĐT Sơn La"}},
        actor_department_id=4,
        employee_name="NGUYỄN ANH TUẤN",
    )
    assert compared["is_member_of_actor_department"] is True
    assert "department_id" not in compared


@pytest.mark.asyncio
async def test_5_named_employee_department_uses_employee_lookup() -> None:
    provider = DirectoryLookupStub(
        employees=[
            ResolvedSubject(
                type=SubjectType.EMPLOYEE,
                employee_id=42,
                employee_name="Lò Văn Định",
                department_id=31,
                department_name="BĐT Sơn La",
            )
        ]
    )
    mention = EntityResolver().extract_subject(
        "Lò Văn Định thuộc đơn vị nào"
    )
    resolution = await SubjectResolver(provider).resolve(mention, _actor())

    assert mention.employee_name == "Lò Văn Định"
    assert resolution.status is SubjectResolutionStatus.RESOLVED
    assert provider.employee_queries == [("Lò Văn Định", None)]
    assert _tool_names(
        Intent.DIRECTORY_EMPLOYEE_DEPARTMENT,
        SubjectType.EMPLOYEE,
    ) == ["employee_get_employment"]


@pytest.mark.asyncio
async def test_6_ambiguous_department_returns_structured_options() -> None:
    provider = DirectoryLookupStub(
        departments=[
            ResolvedSubject(
                type=SubjectType.DEPARTMENT,
                department_id=31,
                department_name="BĐT Sơn La",
            ),
            ResolvedSubject(
                type=SubjectType.DEPARTMENT,
                department_id=32,
                department_name="BĐT TP Sơn La",
            ),
        ]
    )
    resolution = await SubjectResolver(provider).resolve(
        SubjectMention(
            type=SubjectType.DEPARTMENT,
            department_name="Sơn La",
        ),
        _actor(),
    )

    assert resolution.status is SubjectResolutionStatus.AMBIGUOUS
    assert [option.value for option in resolution.options] == [31, 32]
    assert [option.label for option in resolution.options] == [
        "BĐT Sơn La",
        "BĐT TP Sơn La",
    ]


@pytest.mark.asyncio
async def test_7_ambiguous_employees_show_employee_codes() -> None:
    provider = DirectoryLookupStub(
        employees=[
            ResolvedSubject(
                type=SubjectType.EMPLOYEE,
                employee_id=41,
                employee_code="00234086",
                employee_name="NGUYỄN ANH TUẤN",
            ),
            ResolvedSubject(
                type=SubjectType.EMPLOYEE,
                employee_id=42,
                employee_code="00999999",
                employee_name="NGUYỄN ANH TUẤN",
            ),
        ]
    )

    resolution = await SubjectResolver(provider).resolve(
        SubjectMention(
            type=SubjectType.EMPLOYEE,
            employee_name="NGUYỄN ANH TUẤN",
        ),
        _actor(),
    )

    assert resolution.status is SubjectResolutionStatus.AMBIGUOUS
    assert [option.label for option in resolution.options] == [
        "NGUYỄN ANH TUẤN · Mã NV: 00234086",
        "NGUYỄN ANH TUẤN · Mã NV: 00999999",
    ]
