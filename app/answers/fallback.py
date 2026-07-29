from __future__ import annotations

from typing import Any

from app.answers.schemas import FinalAnswerContext
from app.routing.taxonomy import Intent


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
        return "Đã có dữ liệu phù hợp, nhưng chưa thể diễn đạt chi tiết lúc này."

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
