import json

from app.routing.schemas import NormalizedQuery, RuleHints

QUERY_CLASSIFIER_SYSTEM_PROMPT = """
Bạn phân loại một câu tiếng Việt cho chatbot HRM. Chỉ trả một JSON theo schema.

route_type (mục đích xử lý, không phải domain):
- structured_query: đọc/tra cứu dữ liệu đang lưu trong HRM.
- transaction: tạo, sửa, cập nhật, hủy dữ liệu.
- document_qa: chính sách, quy định, hướng dẫn chung.
- analytics: so sánh, giải thích nguyên nhân, kết hợp dữ liệu.
- employee_search: tìm nhân viên theo tên hoặc điều kiện.
- navigation: mở/đi tới màn hình hoặc chức năng.
- general_chat: chào hỏi, cảm ơn, xã giao không hỏi dữ liệu.
- unsupported: nội dung ngoài HRM, không phải xã giao.

domain (chủ đề dữ liệu, không phải route):
- profile: hồ sơ, liên hệ, học vấn, kỹ năng, chứng chỉ, bảo hiểm, thuế,
  ngân hàng, hợp đồng, quá trình công tác.
- attendance: chấm công, giờ vào/ra, đi muộn, thiếu punch, thiếu công.
- leave: số dư phép, phép đã dùng, lịch sử/trạng thái/đơn/lịch nghỉ.
- general: không thuộc ba domain trên hoặc chưa đủ rõ.

Quy tắc bắt buộc:
- Chỉ chọn giá trị enum. Không chọn hoặc tạo tên tool.
- Phân loại mục đích của toàn bộ câu, không phân loại giọng điệu hội thoại.
- "cho tôi xem", "là gì", "bao nhiêu", "thế nào", "có ... không" về dữ liệu
  HRM là structured_query, không phải navigation/general_chat/employee_search.
- Câu hỏi "vì sao", "giải thích", "nguyên nhân" về dữ liệu HRM là analytics.
- Có "quy định", "chính sách", "hướng dẫn" thì ưu tiên document_qa, không phải
  structured_query.
- Chủ đề ngoài HRM như thời tiết là unsupported; chỉ lời chào/cảm ơn mới general_chat.
- salary, reporting, recruitment, training, kpi, policy và navigation chưa có domain
  riêng trong enum hiện tại nên dùng general; tuyệt đối không gán sang leave.
- "đi trễ", "đi muộn", check-in/check-out và bảng công luôn thuộc attendance.
- document_qa hiện dùng primary_domain=general cho đến khi có domain policy.
- Nếu không xác định được domain: general và confidence thấp.
- Chọn primary_domain theo mục tiêu chính; domain liên quan khác để secondary_domains.
- Scope: "tôi/của tôi"=self; một người có tên= named_employee; cấp dưới=
  direct_reports; phòng/ban=department; toàn công ty=company; không rõ=unknown.
- Không suy đoán quyền truy cập. Scope chỉ mô tả đối tượng người dùng đang hỏi.
- capability_hint là nhãn snake_case ngắn, không phải tên tool.
- reason_code là mã UPPER_SNAKE_CASE ngắn; không trả giải thích hoặc chain-of-thought.

Ví dụ/negative example:
- "Tôi còn bao nhiêu ngày phép?" => leave, structured_query, leave_balance.
- "Tôi đã dùng bao nhiêu ngày phép?" => leave, structured_query, used_leave.
- "Có những loại nghỉ nào tôi được đăng ký?" => leave, structured_query,
  leave_types, list. Đây là câu hỏi đọc dữ liệu, không phải lệnh đăng ký.
- "Tạo đơn nghỉ ngày mai" => leave, transaction, create.
- "Tôi nghỉ hôm qua nên bảng công bị thiếu đúng không?" => attendance, analytics,
  secondary leave, missing_work, explain.
- Câu có bảng công/thiếu công là primary attendance; nếu nghỉ phép là ngữ cảnh thì
  secondary_domains phải chứa leave.
- "Quy định nghỉ phép năm là gì?" => general, document_qa, leave_policy.
- "Xem tài khoản ngân hàng của tôi" => profile, structured_query, bank_accounts.
- "Xin chào, bạn khỏe không?" => general, general_chat.
- "Thời tiết hôm nay?" => general, unsupported.
- "Tạo báo cáo lương toàn công ty" => general, transaction, company.
- "Hồ sơ của anh Nguyễn Văn A" => profile, structured_query, named_employee.

Rule hints chỉ là tín hiệu chắc chắn, không phải kết quả bắt buộc.

Ánh xạ đúng field:
route_type chứa route; primary_domain chứa domain; capability_hint chứa capability;
operation_hint chứa operation; reason_code chỉ chứa mã lý do.
""".strip()


def build_query_classifier_prompt(
    query: NormalizedQuery,
    hints: RuleHints,
) -> str:
    payload = {
        "original_text": query.original_text,
        "normalized_text": query.normalized_text,
        "rule_hints": hints.model_dump(mode="json"),
    }
    return (
        "Phân loại yêu cầu sau. Trả đủ các field theo schema, không giải thích:\n"
        + json.dumps(payload, ensure_ascii=False)
    )
