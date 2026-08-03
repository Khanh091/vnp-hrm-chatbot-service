from app.routing.schemas import ValidationIssueCategory

_MESSAGES = {
    "ROUTING_AMBIGUOUS": "Tôi chưa xác định chính xác thông tin bạn muốn tra cứu.",
    "LOW_CONFIDENCE": "Tôi chưa xác định chính xác thông tin bạn muốn tra cứu.",
    "NO_MATCHING_TOOL": "Hiện chatbot chưa hỗ trợ chức năng này.",
    "INTENT_NOT_RECOGNIZED": (
        "Tôi chưa xác định được chính xác yêu cầu của bạn."
    ),
    "NO_CAPABILITY_FOR_INTENT": "Hiện chatbot chưa hỗ trợ chức năng này.",
    "NO_TOOL_FOR_CAPABILITY": "Hiện chatbot chưa hỗ trợ chức năng này.",
    "NO_REGISTERED_TOOL": "Hiện chatbot chưa hỗ trợ chức năng này.",
    "NO_CANDIDATES": "Hiện chatbot chưa hỗ trợ chức năng này.",
    "NO_SUBJECT_COMPATIBLE_TOOL": (
        "Chức năng này chưa hỗ trợ đối tượng bạn muốn tra cứu."
    ),
    "NO_RETRIEVAL_CANDIDATES": "Hiện chatbot chưa hỗ trợ chức năng này.",
    "SUPPORTED_EMPTY": "Hệ thống chưa lưu thông tin này.",
    "INVALID_ARGUMENT": "Thông tin bạn cung cấp chưa hợp lệ.",
    "INVALID_ARGUMENTS": "Thông tin bạn cung cấp chưa hợp lệ.",
    "INVALID_STRUCTURED_SELECTION": (
        "Lựa chọn này không còn hợp lệ. Vui lòng chọn lại từ danh sách hiện tại."
    ),
    "MISSING_ARGUMENT": "Cần bổ sung thêm thông tin.",
    "MISSING_REQUIRED_ARGUMENT": "Cần bổ sung thêm thông tin.",
    "ACCESS_DENIED": "Bạn không có quyền truy cập thông tin này.",
    "SELF_EMPLOYEE_NOT_LINKED": (
        "Tài khoản của bạn chưa được liên kết với hồ sơ nhân viên."
    ),
    "ACTOR_DEPARTMENT_NOT_FOUND": (
        "Hồ sơ nhân viên của bạn chưa có thông tin phòng ban."
    ),
    "SUBJECT_LOOKUP_NOT_AVAILABLE": (
        "Chức năng tra cứu nhân viên hoặc phòng ban hiện chưa khả dụng."
    ),
    "SCOPE_NOT_ALLOWED": "Bạn không có quyền truy cập thông tin này.",
    "SECURITY_REJECTED": "Yêu cầu bị từ chối vì lý do an toàn.",
    "TRUSTED_FIELD_INJECTION": "Yêu cầu bị từ chối vì lý do an toàn.",
    "LLM_RATE_LIMITED": "Hệ thống AI đang tạm thời đạt giới hạn xử lý.",
    "LLM_TIMEOUT": "Hệ thống AI phản hồi chậm. Vui lòng thử lại.",
    "RECORD_NOT_FOUND": "Không tìm thấy đối tượng phù hợp.",
    "ENTITY_NOT_FOUND": "Không tìm thấy đối tượng phù hợp.",
    "ODOO_TIMEOUT": "Hệ thống HRM phản hồi chậm. Vui lòng thử lại.",
    "ODOO_CONNECTION_ERROR": "Không thể kết nối đến hệ thống HRM lúc này.",
    "INVALID_LEAVE_DATE_RANGE": (
        "Khoảng ngày nghỉ không hợp lệ."
    ),
    "LEAVE_REQUEST_NOT_EDITABLE": (
        "Đơn nghỉ này không còn ở trạng thái cho phép sửa."
    ),
    "LEAVE_REQUEST_NOT_CANCELLABLE": (
        "Đơn nghỉ này không còn ở trạng thái cho phép hủy."
    ),
    "LEAVE_REQUEST_OVERLAP": (
        "Khoảng nghỉ mới bị trùng với một đơn nghỉ khác."
    ),
    "LEAVE_REQUEST_NOT_FOUND": (
        "Không tìm thấy đơn nghỉ đã chọn hoặc bạn không còn quyền truy cập."
    ),
    "OVERLAPPING_LEAVE_REQUEST": (
        "Khoảng ngày này trùng với một đơn nghỉ đã có."
    ),
    "INSUFFICIENT_LEAVE_BALANCE": (
        "Số ngày phép khả dụng không đủ cho khoảng nghỉ này."
    ),
    "LEAVE_TYPE_NOT_ALLOWED": (
        "Bạn không thể sử dụng loại nghỉ đã chọn."
    ),
    "LEAVE_TYPE_NOT_FOUND": (
        "Loại nghỉ không còn tồn tại hoặc không còn hiệu lực."
    ),
}

_CATEGORY_DEFAULTS = {
    ValidationIssueCategory.ROUTING: _MESSAGES["ROUTING_AMBIGUOUS"],
    ValidationIssueCategory.ARGUMENT: _MESSAGES["INVALID_ARGUMENT"],
    ValidationIssueCategory.AUTHORIZATION: _MESSAGES["ACCESS_DENIED"],
    ValidationIssueCategory.SECURITY: _MESSAGES["SECURITY_REJECTED"],
    ValidationIssueCategory.PROVIDER: "Hệ thống AI tạm thời chưa sẵn sàng.",
    ValidationIssueCategory.BUSINESS: (
        "Không thể hoàn tất yêu cầu do quy tắc nghiệp vụ."
    ),
}


def public_error_message(
    reason_code: str | None,
    category: ValidationIssueCategory | None = None,
) -> str:
    if reason_code and reason_code in _MESSAGES:
        return _MESSAGES[reason_code]
    if category is not None:
        return _CATEGORY_DEFAULTS[category]
    return "Không thể hoàn tất yêu cầu lúc này."


def category_for_error(reason_code: str | None) -> ValidationIssueCategory:
    if reason_code in {
        "ACCESS_DENIED",
        "SCOPE_NOT_ALLOWED",
        "SUBJECT_NOT_RESOLVED",
        "SUBJECT_CONTEXT_MISMATCH",
        "WRITE_CONFIRMATION_REQUIRED",
        "SELF_EMPLOYEE_NOT_LINKED",
    }:
        return ValidationIssueCategory.AUTHORIZATION
    if reason_code in {
        "SECURITY_REJECTED",
        "TRUSTED_FIELD_INJECTION",
        "TOOL_NOT_ALLOWED",
    }:
        return ValidationIssueCategory.SECURITY
    if reason_code in {
        "INVALID_ARGUMENT",
        "INVALID_ARGUMENTS",
        "MISSING_ARGUMENT",
    }:
        return ValidationIssueCategory.ARGUMENT
    if reason_code in {"LLM_RATE_LIMITED", "LLM_TIMEOUT"}:
        return ValidationIssueCategory.PROVIDER
    if reason_code in {
        "ROUTING_AMBIGUOUS",
        "LOW_CONFIDENCE",
        "NO_MATCHING_TOOL",
        "INTENT_NOT_RECOGNIZED",
        "NO_CAPABILITY_FOR_INTENT",
        "NO_TOOL_FOR_CAPABILITY",
        "NO_SUBJECT_COMPATIBLE_TOOL",
        "NO_RETRIEVAL_CANDIDATES",
    }:
        return ValidationIssueCategory.ROUTING
    return ValidationIssueCategory.BUSINESS
