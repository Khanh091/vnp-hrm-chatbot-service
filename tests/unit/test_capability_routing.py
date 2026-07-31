from __future__ import annotations

import pytest

from app.routing.capabilities import (
    CAPABILITY_REGISTRY,
    CapabilityResolver,
    ToolResolver,
)
from app.routing.intent_refiner import direct_classify_from_exclusive_hints
from app.routing.intent_taxonomy import INTENT_DEFINITIONS
from app.routing.query_normalizer import QueryNormalizer
from app.routing.rules import infer_rule_hints
from app.routing.taxonomy import Intent, Operation, SubjectScope, SubjectType
from app.tools import build_tool_registry
from app.tools.definitions import ToolDefinition


@pytest.mark.parametrize(
    "query",
    (
        "hợp đồng của tôi hết hạn chưa",
        "hợp đồng còn hiệu lực không",
        "hợp đồng bao giờ hết hạn",
    ),
)
def test_contract_expiry_semantics_resolve_self_tool(query: str) -> None:
    normalized = QueryNormalizer().normalize(query)
    classification = direct_classify_from_exclusive_hints(
        normalized,
        infer_rule_hints(normalized),
    )

    assert classification is not None
    assert classification.intent is Intent.PROFILE_CONTRACT_EXPIRY
    assert classification.operation is Operation.READ
    assert classification.scope is SubjectScope.SELF
    tools = _resolve_tools(
        Intent.PROFILE_CONTRACT_EXPIRY,
        SubjectType.SELF,
    )
    assert [tool.name for tool in tools] == ["profile_get_contracts"]
    assert tools[0].capability_name == "employee_contract_read"


def test_contract_summary_resolves_same_self_capability() -> None:
    query = QueryNormalizer().normalize("thông tin hợp đồng của tôi")
    assert all(
        Intent.PROFILE_CONTRACT_EXPIRY not in hint.candidate_intents
        for hint in infer_rule_hints(query).semantic_hints
    )
    tools = _resolve_tools(Intent.PROFILE_CONTRACTS, SubjectType.SELF)

    assert [tool.name for tool in tools] == ["profile_get_contracts"]
    assert tools[0].capability_name == "employee_contract_read"


def test_named_contract_uses_subject_specific_binding() -> None:
    normalized = QueryNormalizer().normalize(
        "hợp đồng của Lò Văn Định hết hạn chưa"
    )
    classification = direct_classify_from_exclusive_hints(
        normalized,
        infer_rule_hints(normalized),
    )

    assert classification is not None
    assert classification.intent is Intent.PROFILE_CONTRACT_EXPIRY
    assert classification.scope is SubjectScope.NAMED_EMPLOYEE
    tools = _resolve_tools(
        Intent.PROFILE_CONTRACT_EXPIRY,
        SubjectType.EMPLOYEE,
    )
    assert [tool.name for tool in tools] == ["employee_get_contracts"]
    assert tools[0].capability_name == "employee_contract_read"


def test_department_employee_intent_resolves_department_capability() -> None:
    query = QueryNormalizer().normalize("nhân viên phòng ban của tôi")
    hinted_intents = {
        intent
        for hint in infer_rule_hints(query).semantic_hints
        for intent in hint.candidate_intents
    }
    tools = _resolve_tools(
        Intent.DIRECTORY_DEPARTMENT_EMPLOYEES,
        SubjectType.DEPARTMENT,
    )

    assert Intent.DIRECTORY_DEPARTMENT_EMPLOYEES in hinted_intents
    assert [tool.name for tool in tools] == ["department_list_employees"]
    assert tools[0].capability_name == "department_employee_list"


def test_department_list_resolves_registered_capability() -> None:
    query = QueryNormalizer().normalize("danh sách phòng ban")
    classification = direct_classify_from_exclusive_hints(
        query,
        infer_rule_hints(query),
    )

    assert classification is not None
    assert classification.intent is Intent.DIRECTORY_DEPARTMENTS
    tools = _resolve_tools(Intent.DIRECTORY_DEPARTMENTS, SubjectType.COMPANY)
    assert [tool.name for tool in tools] == ["department_list"]
    assert tools[0].capability_name == "department_list"


def test_health_has_self_and_named_odoo_tool_bindings() -> None:
    query = QueryNormalizer().normalize("thông tin sức khỏe của tôi")
    hints = infer_rule_hints(query).semantic_hints
    assert any(
        Intent.PROFILE_HEALTH in hint.candidate_intents for hint in hints
    )
    capabilities = CapabilityResolver().resolve(
        intent=Intent.PROFILE_HEALTH,
        subject_type=SubjectType.SELF,
    )

    assert [item.name for item in capabilities] == ["employee_health_read"]
    self_tools = ToolResolver(build_tool_registry()).resolve(
        capability=capabilities[0],
        subject_type=SubjectType.SELF,
    )
    named_tools = ToolResolver(build_tool_registry()).resolve(
        capability=capabilities[0],
        subject_type=SubjectType.EMPLOYEE,
    )
    assert [tool.name for tool in self_tools] == ["profile_get_health"]
    assert [tool.name for tool in named_tools] == ["employee_get_health"]


def test_contract_taxonomy_and_tool_contract_are_consistent() -> None:
    definition = INTENT_DEFINITIONS[Intent.PROFILE_CONTRACT_EXPIRY]
    capability = CAPABILITY_REGISTRY["employee_contract_read"]
    tools = (
        build_tool_registry().get("profile_get_contracts"),
        build_tool_registry().get("employee_get_contracts"),
    )

    assert definition.capability_names == frozenset(
        {"employee_contract_read"}
    )
    assert definition.operation is Operation.READ
    assert capability.supported_intents >= {
        Intent.PROFILE_CONTRACTS,
        Intent.PROFILE_CONTRACT_EXPIRY,
    }
    assert all(tool.intents <= capability.supported_intents for tool in tools)


def _resolve_tools(
    intent: Intent,
    subject_type: SubjectType,
) -> list[ToolDefinition]:
    registry = build_tool_registry()
    capabilities = CapabilityResolver().resolve(
        intent=intent,
        subject_type=subject_type,
    )
    return [
        tool
        for capability in capabilities
        for tool in ToolResolver(registry).resolve(
            capability=capability,
            subject_type=subject_type,
        )
        if tool.supports_intent(intent)
    ]
