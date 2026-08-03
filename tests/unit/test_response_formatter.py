from typing import Any

import pytest

from app.routing.taxonomy import Intent
from app.tools.definitions import ToolExecutionResult
from app.tools.response_formatter import (
    ToolResponseFormatter,
    extract_display_name,
)


def _result(data: dict[str, Any]) -> ToolExecutionResult:
    return ToolExecutionResult(
        tool_name="test",
        success=True,
        data=data,
        latency_ms=1,
    )


@pytest.fixture
def formatter() -> ToolResponseFormatter:
    return ToolResponseFormatter()


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ({"name": "Phòng CNTT"}, "Phòng CNTT"),
        ({"display_name": "Công ty VNPT"}, "Công ty VNPT"),
        ("Giao dịch viên", "Giao dịch viên"),
        (None, None),
        ({"id": 1}, None),
    ],
)
def test_extract_display_name(value: object, expected: str | None) -> None:
    assert extract_display_name(value) == expected


def test_profile_summary_formats_nested_references(
    formatter: ToolResponseFormatter,
) -> None:
    answer = formatter.format(
        "profile_get_summary",
        _result(
            {
                "employee_id": 27909,
                "employee_code": "00022569",
                "full_name": "Nguyễn Thị Thu Phương",
                "birth_date": None,
                "job_title": {"id": 304, "name": "Giao dịch viên"},
                "department": {"id": 31511, "name": "TTDV Hoàn Kiếm"},
                "company": {"id": 1, "name": "My Company"},
                "manager": None,
                "employee_type": {"id": 2, "name": "Nhân viên"},
                "employment_status": {
                    "code": "confirmed",
                    "name": "Xác nhận",
                },
            }
        ),
    )

    assert "Nguyễn Thị Thu Phương" in answer
    assert "Giao dịch viên" in answer
    assert "TTDV Hoàn Kiếm" in answer
    assert "{'id':" not in answer


def test_contact_uses_and_masks_mobile_only(
    formatter: ToolResponseFormatter,
) -> None:
    answer = formatter.format(
        "profile_get_contact",
        _result(
            {
                "work_email": None,
                "other_email": None,
                "work_phone": None,
                "mobile_phone": "0945115161",
                "other_phone": None,
            }
        ),
    )

    assert answer == (
        "Số điện thoại đang lưu của bạn là 0945***161. "
        "Hệ thống chưa có email công việc."
    )


@pytest.mark.parametrize(
    ("tool_name", "data", "expected"),
    [
        (
            "profile_get_certificates",
            {"certificates": [], "professional_certificates": []},
            "Bạn chưa có chứng chỉ nào được lưu trên hệ thống.",
        ),
        (
            "profile_get_skills",
            {"skills": []},
            "Bạn chưa có kỹ năng nào được lưu trên hệ thống.",
        ),
        (
            "profile_get_history",
            {
                "work_history": [],
                "appointment_history": [],
                "transfer_history": [],
            },
            "Chưa có dữ liệu lịch sử phù hợp.",
        ),
    ],
)
def test_empty_profile_collections_have_specific_answers(
    formatter: ToolResponseFormatter,
    tool_name: str,
    data: dict[str, Any],
    expected: str,
) -> None:
    assert formatter.format(tool_name, _result(data)) == expected


def test_contract_history_without_current_is_explicit(
    formatter: ToolResponseFormatter,
) -> None:
    answer = formatter.format(
        "profile_get_contracts",
        _result(
            {
                "current_contract": None,
                "contract_history": [
                    {
                        "id": 93222,
                        "contract_number": "5680/HĐLĐ-BĐHN",
                        "contract_type": {
                            "id": 7,
                            "name": "HĐLĐ Không xác định thời hạn",
                        },
                        "start_date": "2013-10-15",
                        "end_date": None,
                        "state": {"code": "open", "name": "Hiệu lực"},
                    }
                ],
            }
        ),
    )

    assert answer == (
        "Không xác định được hợp đồng hiện tại; hệ thống đang lưu "
        "1 hợp đồng trong lịch sử."
    )


def test_current_contract_formats_allowlisted_fields(
    formatter: ToolResponseFormatter,
) -> None:
    answer = formatter.format(
        "profile_get_contracts",
        _result(
            {
                "current_contract": {
                    "contract_number": "5680/HĐLĐ-BĐHN",
                    "contract_type": {
                        "id": 7,
                        "name": "HĐLĐ Không xác định thời hạn",
                    },
                    "start_date": "2013-10-15",
                    "end_date": None,
                    "state": {"code": "open", "name": "Hiệu lực"},
                },
                "contract_history": [],
            }
        ),
    )

    assert "loại hợp đồng HĐLĐ Không xác định thời hạn" in answer
    assert "mã hợp đồng 5680/HĐLĐ-BĐHN" in answer
    assert "ngày bắt đầu 2013-10-15" in answer
    assert "trạng thái Hiệu lực" in answer


def test_attendance_daily_empty_records(
    formatter: ToolResponseFormatter,
) -> None:
    answer = formatter.format(
        "attendance_get_daily",
        _result(
            {
                "date": "2026-07-27",
                "timezone": "Asia/Saigon",
                "records": [],
            }
        ),
    )

    assert answer == "Không có dữ liệu chấm công trong ngày 2026-07-27."


def test_attendance_daily_reads_nested_records(
    formatter: ToolResponseFormatter,
) -> None:
    answer = formatter.format(
        "attendance_get_daily",
        _result(
            {
                "date": "2026-07-28",
                "timezone": "Asia/Saigon",
                "records": [
                    {
                        "check_in": "2026-07-28T08:00:00+07:00",
                        "check_out": "2026-07-28T17:00:00+07:00",
                        "worked_hours": 8.0,
                    }
                ],
            }
        ),
    )

    assert "2026-07-28T08:00:00+07:00" in answer
    assert "2026-07-28T17:00:00+07:00" in answer
    assert "số giờ làm 8.0" in answer


def test_attendance_monthly_uses_normalized_contract(
    formatter: ToolResponseFormatter,
) -> None:
    answer = formatter.format(
        "attendance_get_monthly_summary",
        _result(
            {
                "month": "2026-08",
                "actual_work_days": 21,
                "valid_attendance_days": 20,
                "missing_punch_days": 0,
                "late_early_days": 0,
                "wrong_shift_days": 0,
                "no_attendance_days": 1,
                "unassigned_shift_worked_days": 8,
                "total_worked_hours": 168.5,
                "overtime_hours": 6.0,
                "late_count": 2,
                "missing_punch_count": 1,
            }
        ),
    )

    assert "20 ngày hợp lệ" in answer
    assert "1 ngày không chấm công" in answer
    assert "8 ngày không phân ca nhưng có đi làm" in answer
    assert "Hệ số ngày công thực tế là 21" in answer
    assert "168.5 giờ làm" in answer
    assert "6.0 giờ tăng ca" in answer


@pytest.mark.parametrize(
    ("intent", "field", "expected"),
    [
        (
            Intent.ATTENDANCE_NO_ATTENDANCE_DAYS,
            "no_attendance_days",
            "1 ngày không chấm công",
        ),
        (
            Intent.ATTENDANCE_UNASSIGNED_SHIFT_WORKED_DAYS,
            "unassigned_shift_worked_days",
            "8 ngày không được phân ca nhưng có đi làm",
        ),
    ],
)
def test_attendance_bucket_formatter(
    formatter: ToolResponseFormatter,
    intent: Intent,
    field: str,
    expected: str,
) -> None:
    answer = formatter.format(
        "attendance_get_monthly_summary",
        _result({"month": "2026-08", field: 1 if "no_" in field else 8}),
        intent=intent,
    )
    assert expected in answer


def test_missing_punch_uses_normalized_count(
    formatter: ToolResponseFormatter,
) -> None:
    answer = formatter.format(
        "attendance_get_missing_punch_summary",
        _result({"missing_punch_count": 3}),
    )

    assert "Có 3 bản ghi" in answer


def test_leave_used_explains_only_approved_usage(
    formatter: ToolResponseFormatter,
) -> None:
    answer = formatter.format(
        "leave_get_used",
        _result({"used_days": 0}),
    )

    assert "0 ngày phép đã được duyệt và trừ vào số dư" in answer
    assert "Đơn nháp hoặc chờ duyệt" in answer
