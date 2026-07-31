from __future__ import annotations

import logging
import unicodedata
from typing import Any

from app.answers.schemas import FinalAnswerContext
from app.routing.taxonomy import Intent

logger = logging.getLogger(__name__)


class DeterministicAnswerFallback:
    def format(self, context: FinalAnswerContext) -> str:
        data = context.data
        if data is None:
            return "Hệ thống chưa lưu thông tin phù hợp với yêu cầu của bạn."
        if isinstance(data, list):
            return (
                "Không có bản ghi phù hợp với yêu cầu của bạn."
                if not data
                else f"Hệ thống có {len(data)} bản ghi phù hợp."
            )
        if context.intent is Intent.PROFILE_MANAGER:
            manager = self._nested(data, "manager")
            name = self._display(manager)
            return (
                f"Quản lý trực tiếp của bạn là {name}."
                if name
                else "Hệ thống chưa lưu thông tin quản lý trực tiếp của bạn."
            )
        if context.intent is Intent.PROFILE_CONTRACT_EXPIRY:
            contract = self._nested(data, "current_contract")
            date_end = (
                contract.get("date_end")
                if isinstance(contract, dict)
                else data.get("date_end")
            )
            return (
                f"Hợp đồng hiện tại của bạn kết thúc vào {date_end}."
                if date_end
                else (
                    "Hợp đồng hiện tại của bạn không có ngày kết thúc "
                    "được lưu trên hệ thống."
                )
            )
        if context.intent is Intent.ATTENDANCE_LATE_COUNT:
            count = data.get("late_count", 0)
            month = data.get("month")
            year = data.get("year")
            period = f"Tháng {month}/{year}, " if month and year else ""
            return (
                f"{period}hệ thống chưa ghi nhận lần đi muộn nào của bạn."
                if count in {0, "0", None}
                else f"{period}bạn có {count} lần đi muộn."
            )
        if context.intent is Intent.PROFILE_PARTY_UNION:
            query = self._fold(context.original_query)
            if "so the dang" in query:
                value = data.get("party_card_number")
                return (
                    f"Số thẻ Đảng đang được lưu của bạn là {value}."
                    if value
                    else "Hệ thống chưa lưu số thẻ Đảng của bạn."
                )
            if "is_party_member" in data:
                value = data["is_party_member"]
                if value is True:
                    return "Bạn hiện được ghi nhận là Đảng viên."
                if value is False:
                    return "Bạn hiện không được ghi nhận là Đảng viên."
                return (
                    "Hệ thống chưa lưu thông tin về việc bạn có là "
                    "Đảng viên hay không."
                )
        if context.intent is Intent.PROFILE_EDUCATION:
            query = self._fold(context.original_query)
            fields = (
                (
                    ("giao duc pho thong",),
                    "general_education",
                    "Trình độ giáo dục phổ thông của bạn là {}.",
                ),
                (
                    ("chuyen nganh",),
                    "major",
                    "Chuyên ngành đang được lưu của bạn là {}.",
                ),
                (
                    ("co so dao tao",),
                    "institution",
                    "Cơ sở đào tạo đang được lưu của bạn là {}.",
                ),
            )
            for concepts, key, template in fields:
                if any(concept in query for concept in concepts):
                    value = data.get(key)
                    return (
                        template.format(value)
                        if value
                        else "Hệ thống chưa lưu thông tin đó."
                    )
            level = data.get("highest_professional_level")
            training_form = data.get("training_form")
            major = data.get("major")
            details = [
                str(value)
                for value in (level, training_form, major)
                if value
            ]
            return (
                "Thông tin trình độ đào tạo của bạn: "
                + ", ".join(details)
                + "."
                if details
                else "Hệ thống chưa lưu thông tin trình độ đào tạo của bạn."
            )
        if context.intent is Intent.PROFILE_ADDRESS:
            query = self._fold(context.original_query)
            if "que quan" in query:
                hometown = data.get("hometown")
                return (
                    f"Quê quán đang được lưu của bạn là {hometown}."
                    if hometown
                    else "Hệ thống chưa lưu thông tin quê quán của bạn."
                )
            current = data.get("current_address")
            if isinstance(current, dict):
                address = (
                    current.get("full_address")
                    or ", ".join(
                        str(value)
                        for value in (
                            current.get("detail"),
                            current.get("ward"),
                            current.get("province"),
                        )
                        if value
                    )
                )
                if address:
                    return (
                        "Nơi ở hiện nay của bạn được lưu tại "
                        f"{address}."
                    )
            return "Hệ thống chưa lưu thông tin nơi ở hiện nay của bạn."
        query = self._fold(context.original_query)
        if context.intent is Intent.PROFILE_FAMILY_RELATIONS:
            items = data.get("items")
            if not isinstance(items, list) or not items:
                return "Hệ thống chưa lưu thông tin quan hệ gia đình của bạn."
            relation_terms = {
                "me": ("me", "mẹ"),
                "cha": ("cha", "cha"),
                "bo": ("bo", "bố"),
            }
            for query_term, labels in relation_terms.items():
                if query_term not in query:
                    continue
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    relationship = self._fold(
                        str(item.get("relationship") or "")
                    )
                    if any(label in relationship for label in labels):
                        name = item.get("full_name")
                        if name:
                            return f"{item.get('relationship')} của bạn là {name}."
                return "Hệ thống chưa lưu thông tin người thân phù hợp."
            details = [
                " - ".join(
                    str(value)
                    for value in (
                        item.get("relationship"),
                        item.get("full_name"),
                    )
                    if value
                )
                for item in items
                if isinstance(item, dict)
            ]
            return (
                "Quan hệ gia đình đang được khai trong hồ sơ của bạn: "
                + "; ".join(details)
                + "."
                if details
                else f"Hồ sơ của bạn có {len(items)} bản ghi quan hệ gia đình."
            )
        if context.intent is Intent.PROFILE_FAMILY_ECONOMY:
            if "thu nhap khac" in query:
                value = data.get("other_income")
                return (
                    f"Nguồn thu nhập khác bạn khai trong hồ sơ là {value}."
                    if value is not None
                    else "Hệ thống chưa lưu nguồn thu nhập khác của bạn."
                )
            if "san xuat" in query or "kinh doanh" in query:
                value = data.get("production_business_assets")
                return (
                    "Thông tin đất/tài sản sản xuất kinh doanh bạn khai là "
                    f"{value}."
                    if value is not None
                    else "Hệ thống chưa lưu thông tin đất/tài sản sản xuất kinh doanh."
                )
            details = [
                detail
                for detail in (
                    (
                        f"lương khai báo {data.get('declared_salary')}"
                        if data.get("declared_salary") is not None
                        else None
                    ),
                    (
                        f"thu nhập khác {data.get('other_income')}"
                        if data.get("other_income") is not None
                        else None
                    ),
                    (
                        "đất/tài sản sản xuất kinh doanh "
                        f"{data.get('production_business_assets')}"
                        if data.get("production_business_assets") is not None
                        else None
                    ),
                )
                if detail is not None
            ]
            return (
                "Thông tin kinh tế gia đình bạn khai trong hồ sơ "
                "(không phải dữ liệu bảng lương): "
                + "; ".join(details)
                + "."
                if details
                else "Hệ thống chưa lưu thông tin kinh tế gia đình của bạn."
            )
        if context.intent is Intent.PROFILE_HEALTH:
            if "nhom mau" in query:
                value = data.get("blood_type")
                return (
                    f"Nhóm máu đang được lưu của bạn là {value}."
                    if value
                    else "Hệ thống chưa lưu nhóm máu của bạn."
                )
            details = [
                detail
                for detail in (
                    (
                        f"tình trạng {data.get('health_status')}"
                        if data.get("health_status") is not None
                        else None
                    ),
                    (
                        f"nhóm máu {data.get('blood_type')}"
                        if data.get("blood_type") is not None
                        else None
                    ),
                    (
                        f"chiều cao {data.get('height_cm')} cm"
                        if data.get("height_cm") is not None
                        else None
                    ),
                    (
                        f"cân nặng {data.get('weight_kg')} kg"
                        if data.get("weight_kg") is not None
                        else None
                    ),
                    (
                        f"tiêm chủng {data.get('vaccination_status')}"
                        if data.get("vaccination_status") is not None
                        else None
                    ),
                )
                if detail is not None
            ]
            if details:
                return "Thông tin sức khỏe của bạn: " + ", ".join(details) + "."
            return "Hệ thống chưa lưu thông tin sức khỏe của bạn."
        if context.intent in {
            Intent.PROFILE_BASIC,
            Intent.PROFILE_SUMMARY,
        }:
            if "ten goi khac" in query or "ten khac" in query or "bi danh" in query:
                value = data.get("other_name")
                return (
                    f"Tên gọi khác đang được lưu của bạn là {value}."
                    if value
                    else "Hệ thống chưa lưu tên gọi khác của bạn."
                )
        if context.intent is Intent.PROFILE_EMPLOYMENT:
            if "cong viec chinh" in query or "nhiem vu chinh" in query:
                value = data.get("primary_assigned_work")
                return (
                    f"Công việc chính được giao của bạn là {value}."
                    if value
                    else "Hệ thống chưa lưu công việc chính được giao của bạn."
                )
        records = data.get("records")
        if isinstance(records, list):
            return (
                "Không có bản ghi phù hợp với yêu cầu của bạn."
                if not records
                else f"Hệ thống có {len(records)} bản ghi phù hợp."
            )
        for key in ("value", "count", "status", "state", "date", "date_end"):
            if key in data:
                value = data[key]
                return (
                    "Hệ thống chưa lưu thông tin phù hợp với yêu cầu của bạn."
                    if value is None
                    else f"Thông tin được ghi nhận là {value}."
                )
        logger.warning(
            "deterministic_answer_fallback "
            "reason_code=UNSUPPORTED_DETERMINISTIC_FORMAT intent=%s "
            "tool_name=%s",
            context.intent.value,
            context.tool_name,
        )
        return "Hệ thống đã tìm thấy dữ liệu phù hợp với yêu cầu của bạn."

    @staticmethod
    def _nested(data: dict[str, object], key: str) -> Any:
        return data.get(key)

    @staticmethod
    def _display(value: Any) -> str | None:
        if isinstance(value, str):
            return value or None
        if isinstance(value, dict):
            name = value.get("name") or value.get("display_name")
            return str(name) if name else None
        return None

    @staticmethod
    def _fold(value: str) -> str:
        decomposed = unicodedata.normalize("NFD", value.lower())
        return " ".join(
            "".join(
                character
                for character in decomposed
                if unicodedata.category(character) != "Mn"
            )
            .replace("đ", "d")
            .split()
        )
