from app.tools.definitions import (
    AttendanceDailyArguments,
    DateRangeArguments,
    Domain,
    HttpMethod,
    Operation,
    RiskLevel,
    RouteType,
    ToolDefinition,
)

_BASE = "/api/hrm-chatbot/v1/attendance/current"


def _attendance_tool(
    *,
    name: str,
    capability: str,
    description: str,
    endpoint: str,
    argument_schema: type[AttendanceDailyArguments] | type[DateRangeArguments],
    examples: tuple[str, ...],
    negative_examples: tuple[str, ...],
) -> ToolDefinition:
    return ToolDefinition(
        name=name,
        domain=Domain.ATTENDANCE,
        capability=capability,
        operation=Operation.GET,
        route_type=RouteType.QUERY,
        risk_level=RiskLevel.READ,
        description=description,
        endpoint=f"{_BASE}/{endpoint}",
        http_method=HttpMethod.POST,
        argument_schema=argument_schema,
        examples=examples,
        negative_examples=negative_examples,
    )


ATTENDANCE_TOOLS = (
    _attendance_tool(
        name="attendance_get_daily",
        capability="attendance.daily",
        description="Lấy chi tiết chấm công của một ngày cụ thể.",
        endpoint="daily",
        argument_schema=AttendanceDailyArguments,
        examples=(
            "Chấm công ngày 15 tháng 7 của tôi thế nào?",
            "Hôm qua tôi vào và ra lúc mấy giờ?",
            "Cho xem chi tiết công của ngày 2026-07-20.",
            "Ngày thứ hai vừa rồi tôi làm bao nhiêu giờ?",
            "Kiểm tra trạng thái chấm công hôm nay.",
        ),
        negative_examples=(
            "Tổng hợp chấm công tháng này.",
            "Các lần đi muộn trong tuần qua.",
            "Ngày nào tháng này tôi thiếu lượt chấm?",
        ),
    ),
    _attendance_tool(
        name="attendance_get_monthly_summary",
        capability="attendance.monthly_summary",
        description="Tổng hợp công trong một khoảng ngày thuộc kỳ cần xem.",
        endpoint="monthly-summary",
        argument_schema=DateRangeArguments,
        examples=(
            "Tổng hợp chấm công tháng 7 của tôi.",
            "Tháng này tôi làm đủ bao nhiêu ngày?",
            "Cho bảng tổng kết công từ đầu đến cuối tháng.",
            "Tổng số giờ làm trong kỳ vừa rồi.",
            "Xem thống kê ngày công tháng trước.",
        ),
        negative_examples=(
            "Chi tiết chấm công hôm nay.",
            "Tôi đi muộn bao nhiêu lần tháng này?",
            "Giải thích vì sao tôi bị thiếu công.",
        ),
    ),
    _attendance_tool(
        name="attendance_get_history",
        capability="attendance.history",
        description="Lấy các bản ghi chấm công trong một khoảng thời gian.",
        endpoint="history",
        argument_schema=DateRangeArguments,
        examples=(
            "Cho xem lịch sử chấm công tuần này.",
            "Liệt kê các ngày công từ 1 đến 15 tháng 7.",
            "Tôi muốn xem từng bản ghi vào ra tháng trước.",
            "Tra cứu lịch sử check-in và check-out gần đây.",
            "Danh sách chấm công của tôi trong quý này.",
        ),
        negative_examples=(
            "Tóm tắt tổng ngày công tháng này.",
            "Thống kê riêng các lần đi muộn.",
            "Tôi còn bao nhiêu ngày phép?",
        ),
    ),
    _attendance_tool(
        name="attendance_get_late_summary",
        capability="attendance.late_summary",
        description="Tổng hợp các lần và thời lượng đi muộn.",
        endpoint="late-summary",
        argument_schema=DateRangeArguments,
        examples=(
            "Tháng này tôi đi muộn bao nhiêu lần?",
            "Tổng thời gian đến trễ trong tuần qua.",
            "Cho thống kê các ngày tôi check-in muộn.",
            "Tôi có bị ghi nhận đi trễ trong kỳ này không?",
            "Tóm tắt tình trạng đi làm muộn tháng trước.",
        ),
        negative_examples=(
            "Tôi có những ngày nào thiếu chấm ra?",
            "Tổng số giờ làm việc tháng này.",
            "Chi tiết giờ vào ra của hôm qua.",
        ),
    ),
    _attendance_tool(
        name="attendance_get_missing_punch_summary",
        capability="attendance.missing_punch_summary",
        description="Tổng hợp các ngày thiếu lượt chấm vào hoặc chấm ra.",
        endpoint="missing-punch-summary",
        argument_schema=DateRangeArguments,
        examples=(
            "Tháng này tôi thiếu chấm công ngày nào?",
            "Cho biết các lần quên check-out.",
            "Tổng hợp bản ghi thiếu giờ vào hoặc giờ ra.",
            "Tuần qua tôi có ngày nào thiếu lượt chấm không?",
            "Liệt kê lỗi thiếu punch trong kỳ công.",
        ),
        negative_examples=(
            "Vì sao hệ thống tính tôi thiếu công?",
            "Tổng hợp các lần tôi đi muộn.",
            "Chi tiết chấm công của một ngày.",
        ),
    ),
    _attendance_tool(
        name="attendance_get_missing_work_context",
        capability="attendance.missing_work_context",
        description="Lấy ngữ cảnh giải thích các ngày bị thiếu công.",
        endpoint="missing-work-context",
        argument_schema=DateRangeArguments,
        examples=(
            "Vì sao tháng này tôi bị tính thiếu công?",
            "Giải thích những ngày công không đủ của tôi.",
            "Cho ngữ cảnh các bản ghi bị đánh dấu thiếu giờ.",
            "Ngày công bất thường của tôi có lý do gì?",
            "Phân tích các ngày hệ thống ghi nhận thiếu làm việc.",
        ),
        negative_examples=(
            "Liệt kê ngày thiếu chấm vào hoặc chấm ra.",
            "Tổng số ngày công trong tháng.",
            "Tôi đi muộn mấy lần tuần này?",
        ),
    ),
)
