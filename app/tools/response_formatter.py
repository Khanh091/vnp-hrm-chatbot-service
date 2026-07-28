from collections.abc import Callable
from typing import Any

from app.tools.definitions import ToolExecutionResult

Formatter = Callable[[dict[str, Any]], str]


def _first(data: dict[str, Any], *names: str, default: Any = "—") -> Any:
    for name in names:
        if data.get(name) is not None:
            return data[name]
    return default


class ToolResponseFormatter:
    def __init__(self) -> None:
        self._formatters: dict[str, Formatter] = {
            "profile_get_summary": lambda d: (
                f"Hồ sơ của bạn: mã nhân viên "
                f"{_first(d, 'employee_code', 'code')}, "
                f"{_first(d, 'name', 'employee_name')}."
            ),
            "profile_get_employment": lambda d: (
                f"Vị trí hiện tại của bạn là "
                f"{_first(d, 'job_title', 'position_name')}, thuộc "
                f"{_first(d, 'department_name', 'department')}."
            ),
            "profile_get_contact": lambda d: (
                f"Thông tin liên hệ đang lưu: email "
                f"{_first(d, 'work_email', 'email')}, số điện thoại "
                f"{_first(d, 'work_phone', 'phone')}."
            ),
            "attendance_get_daily": lambda d: (
                f"Chấm công ngày {_first(d, 'date')}: vào "
                f"{_first(d, 'check_in', 'time_in')}, ra "
                f"{_first(d, 'check_out', 'time_out')}."
            ),
            "attendance_get_monthly_summary": lambda d: (
                f"Tổng hợp kỳ công: {_first(d, 'worked_days', 'total_days')} "
                f"ngày công, {_first(d, 'worked_hours', 'total_hours')} giờ."
            ),
            "attendance_get_late_summary": lambda d: (
                f"Bạn có {_first(d, 'late_count', 'count', default=0)} "
                "lần đi muộn trong kỳ."
            ),
            "attendance_get_missing_punch_summary": lambda d: (
                f"Có {_first(d, 'missing_count', 'count', default=0)} "
                "bản ghi thiếu chấm vào hoặc chấm ra."
            ),
            "leave_get_balance": lambda d: (
                f"Bạn còn {_first(d, 'remaining_days', 'balance')} ngày "
                f"{_first(d, 'leave_type_name', default='phép')}."
            ),
            "leave_get_used": lambda d: (
                f"Bạn đã sử dụng {_first(d, 'used_days', 'used')} ngày "
                f"{_first(d, 'leave_type_name', default='phép')}."
            ),
            "leave_get_request_status": lambda d: (
                f"Đơn nghỉ {_first(d, 'request_code', 'request_id')} đang ở "
                f"trạng thái {_first(d, 'state_name', 'state')}."
            ),
        }

    def format(
        self,
        tool_name: str,
        result: ToolExecutionResult,
    ) -> str:
        if not result.success:
            return "Không thể truy xuất dữ liệu HRM lúc này."
        data = result.data if isinstance(result.data, dict) else {}
        formatter = self._formatters.get(tool_name)
        if formatter is None:
            return "Đã truy xuất dữ liệu HRM thành công."
        return formatter(data)
