_QUESTIONS = {
    "date": "Bạn muốn xem dữ liệu của ngày nào?",
    "date_from": "Bạn muốn bắt đầu nghỉ từ ngày nào?",
    "date_to": "Bạn muốn nghỉ đến ngày nào?",
    "leave_type_id": "Bạn muốn sử dụng loại nghỉ nào?",
    "reason": "Bạn muốn ghi lý do nghỉ là gì?",
    "request_id": "Bạn muốn thao tác với đơn nghỉ nào?",
}


def clarification_question(field: str) -> str:
    return _QUESTIONS.get(field, f"Bạn vui lòng cung cấp {field}.")
