from __future__ import annotations

from app.answers.fallback import DeterministicAnswerFallback
from app.answers.schemas import FinalAnswerContext
from app.routing.capabilities import CapabilityResolver, ToolResolver
from app.routing.intent_refiner import direct_classify_from_exclusive_hints
from app.routing.query_normalizer import QueryNormalizer
from app.routing.rules import infer_rule_hints
from app.routing.taxonomy import Intent, SubjectType
from app.tools import build_tool_registry
from app.tools.definitions import RiskLevel


def _resolve(query: str):
    normalized = QueryNormalizer().normalize(query)
    classification = direct_classify_from_exclusive_hints(
        normalized,
        infer_rule_hints(normalized),
    )
    assert classification is not None
    capability = CapabilityResolver().resolve(
        intent=classification.intent,
        subject_type=SubjectType.SELF,
    )
    assert len(capability) == 1
    tools = ToolResolver(build_tool_registry()).resolve(
        capability=capability[0],
        subject_type=SubjectType.SELF,
    )
    assert len(tools) == 1
    return classification, capability[0], tools[0]


def _answer(query: str, intent: Intent, tool_name: str, data: dict) -> str:
    return DeterministicAnswerFallback().format(
        FinalAnswerContext(
            original_query=query,
            route="data_query",
            intent=intent,
            operation="read",
            tool_name=tool_name,
            data=data,
            locale="vi_VN",
            timezone="Asia/Ho_Chi_Minh",
        )
    )


def test_1_me_cua_toi_la_ai() -> None:
    query = "mẹ của tôi là ai"
    classification, capability, tool = _resolve(query)
    assert classification.intent is Intent.PROFILE_FAMILY_RELATIONS
    assert capability.name == "employee_family_relations_read"
    assert capability.risk_level is RiskLevel.FAMILY_RELATIONS_READ
    assert tool.name == "profile_get_family_relations"
    assert tool.endpoint.endswith("/profile/current/family-relations")
    answer = _answer(
        query,
        classification.intent,
        tool.name,
        {
            "items": [
                {
                    "relationship": "Mẹ đẻ",
                    "full_name": "Lò Thị Lò",
                    "birth_date": "1980-02-05",
                    "address": "Sơn La",
                    "occupation": None,
                }
            ]
        },
    )
    assert answer == "Mẹ đẻ của bạn là Lò Thị Lò."


def test_2_quan_he_gia_dinh_cua_toi() -> None:
    query = "quan hệ gia đình của tôi"
    classification, capability, tool = _resolve(query)
    assert classification.intent is Intent.PROFILE_FAMILY_RELATIONS
    assert capability.name == "employee_family_relations_read"
    answer = _answer(
        query,
        classification.intent,
        tool.name,
        {
            "items": [
                {
                    "relationship": "Mẹ đẻ",
                    "full_name": "Lò Thị Lò",
                    "birth_date": "1980-02-05",
                    "address": "Sơn La",
                    "occupation": None,
                }
            ]
        },
    )
    assert "Mẹ đẻ - Lò Thị Lò" in answer


def test_3_cac_nguon_thu_nhap_khac_cua_toi() -> None:
    query = "các nguồn thu nhập khác của tôi"
    classification, capability, tool = _resolve(query)
    assert classification.intent is Intent.PROFILE_FAMILY_ECONOMY
    assert capability.name == "employee_family_economy_read"
    assert capability.risk_level is RiskLevel.FAMILY_ECONOMY_READ
    assert tool.name == "profile_get_family_economy"
    answer = _answer(
        query,
        classification.intent,
        tool.name,
        {
            "declared_salary": 20_000_000,
            "other_income": 20_000_000,
            "production_business_assets": "Kinh doanh tự do pc, vợt",
        },
    )
    assert "20000000" in answer
    assert "khai trong hồ sơ" in answer
    assert "Kinh doanh tự do" not in answer


def test_4_dat_san_xuat_kinh_doanh_cua_toi() -> None:
    query = "đất sản xuất kinh doanh của tôi"
    classification, capability, tool = _resolve(query)
    assert classification.intent is Intent.PROFILE_FAMILY_ECONOMY
    assert capability.name == "employee_family_economy_read"
    answer = _answer(
        query,
        classification.intent,
        tool.name,
        {
            "declared_salary": 20_000_000,
            "other_income": 20_000_000,
            "production_business_assets": "Kinh doanh tự do pc, vợt",
        },
    )
    assert "Kinh doanh tự do pc, vợt" in answer
    assert "20000000" not in answer


def test_5_nhom_mau_cua_toi() -> None:
    query = "nhóm máu của tôi"
    classification, capability, tool = _resolve(query)
    assert classification.intent is Intent.PROFILE_HEALTH
    assert capability.name == "employee_health_read"
    assert capability.risk_level is RiskLevel.HEALTH_READ
    assert tool.name == "profile_get_health"
    answer = _answer(
        query,
        classification.intent,
        tool.name,
        {
            "health_status": "Tốt",
            "blood_type": "A",
            "height_cm": 173,
            "weight_kg": 58,
            "vaccination_status": "Mũi 4",
            "examinations": [],
            "vaccinations": [],
        },
    )
    assert answer == "Nhóm máu đang được lưu của bạn là A."


def test_6_thong_tin_suc_khoe_cua_toi() -> None:
    query = "thông tin sức khỏe của tôi"
    classification, capability, tool = _resolve(query)
    assert classification.intent is Intent.PROFILE_HEALTH
    assert capability.name == "employee_health_read"
    answer = _answer(
        query,
        classification.intent,
        tool.name,
        {
            "health_status": "Tốt",
            "blood_type": "A",
            "height_cm": 0,
            "weight_kg": 58,
            "vaccination_status": "Mũi 4",
            "examinations": [],
            "vaccinations": [],
        },
    )
    assert "tình trạng Tốt" in answer
    assert "nhóm máu A" in answer
    assert "chiều cao 0 cm" in answer
    assert "cân nặng 58 kg" in answer


def test_7_cong_viec_chinh_duoc_giao_cua_toi() -> None:
    query = "công việc chính được giao của tôi"
    classification, capability, tool = _resolve(query)
    assert classification.intent is Intent.PROFILE_EMPLOYMENT
    assert capability.name == "employee_employment_read"
    assert tool.name == "profile_get_employment"
    answer = _answer(
        query,
        classification.intent,
        tool.name,
        {
            "employee_type": "Nhân viên",
            "is_manager": True,
            "concurrent_titles": [],
            "concurrent_positions": [],
            "primary_assigned_work": "Làm chatbot cho VNPost",
        },
    )
    assert answer == (
        "Công việc chính được giao của bạn là Làm chatbot cho VNPost."
    )


def test_8_ten_goi_khac_cua_toi() -> None:
    query = "tên gọi khác của tôi"
    classification, capability, tool = _resolve(query)
    assert classification.intent is Intent.PROFILE_BASIC
    assert capability.name == "employee_basic_read"
    assert tool.name == "profile_get_summary"
    answer = _answer(
        query,
        classification.intent,
        tool.name,
        {"other_name": "Định Lò"},
    )
    assert answer == "Tên gọi khác đang được lưu của bạn là Định Lò."
