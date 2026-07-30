from __future__ import annotations

from typing import Any

import pytest

from app.answers.context_builder import AnswerContextBuilder
from app.answers.fallback import DeterministicAnswerFallback
from app.answers.sanitizer import ToolResultSanitizer
from app.routing.intent_refiner import direct_classify_from_exclusive_hints
from app.routing.query_normalizer import QueryNormalizer
from app.routing.rules import infer_rule_hints
from app.routing.taxonomy import Intent
from app.tools import build_tool_registry
from app.tools.definitions import ToolExecutionResult

PARTY_DATA = {
    "is_party_member": True,
    "party_card_number": "PARTY-CARD-FIXTURE",
    "party_card_issue_date": "2026-07-01",
    "probationary_join_date": "2026-07-01",
    "official_join_date": "2027-07-01",
    "party_organization": "Party organization fixture",
    "party_history": [{"activity": "Party history fixture"}],
    "is_union_member": False,
    "union_join_date": None,
    "union_history": [],
}
EDUCATION_DATA = {
    "general_education": "12/12",
    "education_system": "THPT",
    "highest_professional_level": "Đại học",
    "training_form": "Chính quy",
    "major": "Công nghệ thông tin",
    "graduation_year": 2027,
    "institution": "Cơ sở đào tạo fixture",
    "political_theory_level": None,
    "professional_records": [],
    "education": [],
}
ADDRESS_DATA = {
    "permanent_address": None,
    "current_address": {
        "province": "TP. Hà Nội",
        "ward": "Phường Hoàn Kiếm",
        "detail": None,
        "full_address": "Phường Hoàn Kiếm, TP. Hà Nội",
    },
    "hometown": "Quê quán fixture",
}


@pytest.mark.parametrize(
    ("query", "intent", "tool_name", "raw_data", "answer_fragment"),
    (
        (
            "tôi có là đảng viên không",
            Intent.PROFILE_PARTY_UNION,
            "profile_get_party_union",
            PARTY_DATA,
            "được ghi nhận là Đảng viên",
        ),
        (
            "số thẻ Đảng của tôi",
            Intent.PROFILE_PARTY_UNION,
            "profile_get_party_union",
            PARTY_DATA,
            "PARTY-CARD-FIXTURE",
        ),
        (
            "trình độ giáo dục phổ thông của tôi",
            Intent.PROFILE_EDUCATION,
            "profile_get_education",
            EDUCATION_DATA,
            "12/12",
        ),
        (
            "trình độ đào tạo của tôi",
            Intent.PROFILE_EDUCATION,
            "profile_get_education",
            EDUCATION_DATA,
            "Đại học",
        ),
        (
            "chuyên ngành của tôi",
            Intent.PROFILE_EDUCATION,
            "profile_get_education",
            EDUCATION_DATA,
            "Công nghệ thông tin",
        ),
        (
            "cơ sở đào tạo của tôi",
            Intent.PROFILE_EDUCATION,
            "profile_get_education",
            EDUCATION_DATA,
            "Cơ sở đào tạo fixture",
        ),
        (
            "nơi ở hiện nay của tôi",
            Intent.PROFILE_ADDRESS,
            "profile_get_addresses",
            ADDRESS_DATA,
            "Phường Hoàn Kiếm, TP. Hà Nội",
        ),
        (
            "quê quán của tôi",
            Intent.PROFILE_ADDRESS,
            "profile_get_addresses",
            ADDRESS_DATA,
            "Quê quán fixture",
        ),
    ),
)
def test_profile_data_trace_stages(
    query: str,
    intent: Intent,
    tool_name: str,
    raw_data: dict[str, Any],
    answer_fragment: str,
) -> None:
    normalized = QueryNormalizer().normalize(query)
    classification = direct_classify_from_exclusive_hints(
        normalized,
        infer_rule_hints(normalized),
    )
    assert classification is not None
    assert classification.intent is intent

    tools = build_tool_registry().find_tools(
        intent=classification.intent,
        domain=classification.domain.value if classification.domain else None,
        route=classification.route,
        operation=classification.operation,
        scope=classification.scope,
    )
    assert [tool.name for tool in tools] == [tool_name]
    endpoint = tools[0].endpoint

    builder = AnswerContextBuilder(
        ToolResultSanitizer(max_items=20, max_chars=12000)
    )
    context = builder.build(
        original_query=query,
        classification=classification,
        tool_name=tool_name,
        tool_result=ToolExecutionResult(
            tool_name=tool_name,
            success=True,
            data=raw_data,
            latency_ms=1,
        ),
        locale="vi_VN",
        timezone="Asia/Ho_Chi_Minh",
    )
    answer = DeterministicAnswerFallback().format(context)

    trace = {
        "classification": classification.intent.value,
        "selected_tool": tool_name,
        "odoo_endpoint": endpoint,
        "odoo_raw_business_keys": sorted(raw_data),
        "sanitized_keys": sorted(context.data or {}),
        "final_answer": answer,
    }
    assert trace["classification"] == intent.value
    assert endpoint.startswith(("/api/hrm-chatbot/v1/", "/api/v1/hrm/"))
    assert trace["odoo_raw_business_keys"] == trace["sanitized_keys"]
    assert answer_fragment in answer
