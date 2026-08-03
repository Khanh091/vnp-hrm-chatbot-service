import logging
from collections.abc import Callable
from typing import Any

from app.routing.taxonomy import Intent
from app.tools.definitions import ToolExecutionResult

logger = logging.getLogger(__name__)

Formatter = Callable[[dict[str, Any]], str]
EMPTY_VALUE = "—"


def extract_display_name(value: object) -> str | None:
    if isinstance(value, str):
        normalized = value.strip()
        return normalized or None
    if isinstance(value, dict):
        for field_name in ("name", "display_name"):
            display_name = value.get(field_name)
            if isinstance(display_name, str) and display_name.strip():
                return display_name.strip()
    return None


def _first(data: dict[str, Any], *names: str, default: Any = EMPTY_VALUE) -> Any:
    for name in names:
        value = data.get(name)
        if value is not None and value != "":
            return value
    return default


def _display(value: object) -> str:
    display_name = extract_display_name(value)
    if display_name is not None:
        return display_name
    if value is None:
        return EMPTY_VALUE
    if isinstance(value, (int, float)):
        return str(value)
    return EMPTY_VALUE


def _mask_phone(value: object) -> str | None:
    phone = extract_display_name(value)
    if phone is None:
        return None
    if "*" in phone:
        return phone
    if len(phone) <= 7:
        return ("*" * max(len(phone) - 3, 0)) + phone[-3:]
    return f"{phone[:4]}***{phone[-3:]}"


def _format_profile_summary(data: dict[str, Any]) -> str:
    return (
        f"Hồ sơ của bạn: họ tên {_display(data.get('full_name'))}, "
        f"mã nhân viên {_display(data.get('employee_code'))}, "
        f"ngày sinh {_display(data.get('birth_date'))}, "
        f"chức danh {_display(data.get('job_title'))}, "
        f"phòng ban {_display(data.get('department'))}, "
        f"đơn vị {_display(data.get('company'))}, "
        f"quản lý trực tiếp {_display(data.get('manager'))}, "
        f"loại nhân sự {_display(data.get('employee_type'))}, "
        f"trạng thái {_display(data.get('employment_status'))}."
    )


def _format_profile_employment(data: dict[str, Any]) -> str:
    manager = data.get("manager", data.get("direct_manager"))
    employment_status = data.get(
        "employment_status",
        data.get("work_status"),
    )
    return (
        f"Thông tin công tác: chức danh {_display(data.get('job_title'))}, "
        f"vị trí {_display(data.get('position'))}, "
        f"phòng ban {_display(data.get('department'))}, "
        f"đơn vị {_display(data.get('company'))}, "
        f"quản lý trực tiếp {_display(manager)}, "
        f"trạng thái {_display(employment_status)}."
    )


def _format_profile_contact(data: dict[str, Any]) -> str:
    email = _first(data, "work_email", "other_email", default=None)
    phone = _first(
        data,
        "work_phone",
        "mobile_phone",
        "other_phone",
        default=None,
    )
    masked_phone = _mask_phone(phone)
    if email and masked_phone:
        return (
            f"Email đang lưu của bạn là {email}. "
            f"Số điện thoại đang lưu là {masked_phone}."
        )
    if masked_phone:
        return (
            f"Số điện thoại đang lưu của bạn là {masked_phone}. "
            "Hệ thống chưa có email công việc."
        )
    if email:
        return f"Email đang lưu của bạn là {email}. Hệ thống chưa có số điện thoại."
    return "Hệ thống chưa có email hoặc số điện thoại của bạn."


def _format_profile_history(data: dict[str, Any]) -> str:
    groups = (
        data.get("work_history"),
        data.get("appointment_history"),
        data.get("transfer_history"),
    )
    total = sum(len(group) for group in groups if isinstance(group, list))
    if total == 0:
        return "Chưa có dữ liệu lịch sử phù hợp."
    return f"Hệ thống đang lưu {total} bản ghi lịch sử công tác phù hợp."


def _format_certificates(data: dict[str, Any]) -> str:
    certificates = data.get("certificates")
    professional = data.get("professional_certificates")
    rows = [
        row
        for collection in (certificates, professional)
        if isinstance(collection, list)
        for row in collection
        if isinstance(row, dict)
    ]
    if not rows:
        return "Bạn chưa có chứng chỉ nào được lưu trên hệ thống."
    names = [_display(row.get("name")) for row in rows]
    return f"Chứng chỉ đang lưu: {', '.join(names)}."


def _format_skills(data: dict[str, Any]) -> str:
    skills = data.get("skills")
    if not isinstance(skills, list) or not skills:
        return "Bạn chưa có kỹ năng nào được lưu trên hệ thống."
    names = [_display(row.get("skill")) for row in skills if isinstance(row, dict)]
    return f"Kỹ năng đang lưu: {', '.join(names)}."


def _format_contract_row(contract: dict[str, Any]) -> str:
    return (
        f"loại hợp đồng {_display(contract.get('contract_type'))}, "
        f"mã hợp đồng {_display(contract.get('contract_number'))}, "
        f"ngày bắt đầu {_display(contract.get('start_date'))}, "
        f"ngày kết thúc {_display(contract.get('end_date'))}, "
        f"trạng thái {_display(contract.get('state'))}"
    )


def _format_contracts(data: dict[str, Any]) -> str:
    current_contract = data.get("current_contract")
    history = data.get("contract_history")
    history_count = len(history) if isinstance(history, list) else 0
    if isinstance(current_contract, dict):
        return f"Hợp đồng hiện tại: {_format_contract_row(current_contract)}."
    if history_count:
        return (
            "Không xác định được hợp đồng hiện tại; hệ thống đang lưu "
            f"{history_count} hợp đồng trong lịch sử."
        )
    return "Hệ thống chưa có hợp đồng lao động nào được lưu."


def _format_attendance_daily(data: dict[str, Any]) -> str:
    work_date = _display(data.get("date"))
    records = data.get("records")
    if not isinstance(records, list) or not records:
        return f"Không có dữ liệu chấm công trong ngày {work_date}."
    details = []
    for record in records:
        if not isinstance(record, dict):
            continue
        details.append(
            f"vào {_display(record.get('check_in'))}, "
            f"ra {_display(record.get('check_out'))}, "
            f"số giờ làm {_display(record.get('worked_hours'))}"
        )
    if not details:
        return f"Không có dữ liệu chấm công trong ngày {work_date}."
    return f"Chấm công ngày {work_date}: {'; '.join(details)}."


def _format_attendance_monthly(
    data: dict[str, Any], intent: Intent | str | None = None
) -> str:
    logger.info(
        "attendance_monthly intent=%s source=%s fields=%s",
        getattr(intent, "value", intent),
        data.get("source"),
        sorted(
            key
            for key in (
                "month",
                "actual_work_days",
                "attendance_record_days",
                "total_worked_hours",
                "source",
            )
            if key in data
        ),
    )
    if intent in {Intent.ATTENDANCE_RECORDED_DAYS, "attendance.recorded_days"}:
        return (
            f"Tháng {_display(data.get('month'))}, bạn có "
            f"{_display(data.get('attendance_record_days'))} ngày có bản ghi chấm công."
        )
    if intent in {
        Intent.ATTENDANCE_ACTUAL_WORK_DAYS,
        "attendance.actual_work_days",
    }:
        return (
            f"Tháng {_display(data.get('month'))}, bạn có "
            f"{_display(data.get('actual_work_days'))} ngày công thực tế."
        )
    return (
        f"Tổng hợp kỳ công tháng {_display(data.get('month'))}: "
        f"{_display(data.get('actual_work_days'))} ngày công thực tế, "
        f"{_display(data.get('attendance_record_days'))} ngày có bản ghi chấm công, "
        f"{_display(data.get('total_worked_hours'))} giờ làm, "
        f"{_display(data.get('overtime_hours'))} giờ tăng ca, "
        f"{_display(data.get('late_count'))} lần đi muộn, "
        f"{_display(data.get('missing_punch_count'))} lần thiếu chấm công."
    )


def _format_leave_balance(data: dict[str, Any]) -> str:
    keys = {
        key
        for key in (
            "allocated_days",
            "approved_used_days",
            "pending_days",
            "remaining_days",
            "available_days",
            "validity",
        )
        if key in data
    }
    logger.info("leave_balance breakdown_keys=%s", sorted(keys))
    remaining = data.get("remaining_days")
    available = data.get("available_days")
    if all(
        data.get(key) is not None
        for key in ("remaining_days", "pending_days", "available_days")
    ):
        return (
            f"Bạn còn {remaining} ngày phép theo phân bổ. Trong đó "
            f"{data['pending_days']} ngày đang được giữ cho các đơn chờ xử lý, "
            f"nên hiện có {available} ngày khả dụng."
        )
    logger.warning(
        "leave_balance pending_breakdown_missing breakdown_keys=%s", sorted(keys)
    )
    if remaining is not None and available is not None:
        return (
            f"Bạn còn {remaining} ngày phép. Hệ thống hiện tính "
            f"{available} ngày có thể sử dụng ngay."
        )
    return f"Bạn còn {_first(data, 'remaining_days', 'balance')} ngày phép."


class ToolResponseFormatter:
    def __init__(self) -> None:
        self._formatters: dict[str, Formatter] = {
            "profile_get_summary": _format_profile_summary,
            "profile_get_employment": _format_profile_employment,
            "profile_get_contact": _format_profile_contact,
            "profile_get_history": _format_profile_history,
            "profile_get_certificates": _format_certificates,
            "profile_get_skills": _format_skills,
            "profile_get_contracts": _format_contracts,
            "attendance_get_daily": _format_attendance_daily,
            "attendance_get_monthly_summary": _format_attendance_monthly,
            "attendance_get_late_summary": lambda data: (
                f"Bạn có {_first(data, 'late_count', default=0)} lần đi muộn trong kỳ."
            ),
            "attendance_get_missing_punch_summary": lambda data: (
                f"Có {_first(data, 'missing_punch_count', default=0)} "
                "bản ghi thiếu chấm vào hoặc chấm ra."
            ),
            "leave_get_balance": _format_leave_balance,
            "leave_get_used": lambda data: (
                f"Bạn đã sử dụng {_first(data, 'used_days', 'used')} ngày "
                f"{_first(data, 'leave_type_name', default='phép')}."
            ),
            "leave_get_request_status": lambda data: (
                f"Đơn nghỉ {_first(data, 'request_code', 'request_id')} đang ở "
                f"trạng thái {_first(data, 'state_name', 'state')}."
            ),
        }

    def format(
        self,
        tool_name: str,
        result: ToolExecutionResult,
        *,
        intent: Intent | str | None = None,
    ) -> str:
        if not result.success:
            return "Không thể truy xuất dữ liệu HRM lúc này."
        data = result.data if isinstance(result.data, dict) else {}
        formatter = self._formatters.get(tool_name)
        if formatter is None:
            return "Đã truy xuất dữ liệu HRM thành công."
        if tool_name == "attendance_get_monthly_summary":
            return _format_attendance_monthly(data, intent)
        return formatter(data)
