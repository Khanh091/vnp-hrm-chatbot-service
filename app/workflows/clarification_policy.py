_QUESTIONS = {
    "date": "Bạn muốn xem dữ liệu của ngày nào?",
    "date_from": "Bạn muốn tra cứu từ ngày nào?",
    "date_to": "Bạn muốn tra cứu đến ngày nào?",
    "leave_type_id": "Bạn muốn sử dụng loại nghỉ nào?",
    "reason": "Bạn muốn ghi lý do nghỉ là gì?",
    "request_id": "Bạn muốn thao tác với đơn nghỉ nào?",
    "employee_id": "Bạn muốn tra cứu nhân viên nào?",
    "department_id": "Bạn muốn xem phòng ban nào?",
}


def clarification_question(field: str) -> str:
    return _QUESTIONS.get(field, f"Bạn vui lòng cung cấp {field}.")
