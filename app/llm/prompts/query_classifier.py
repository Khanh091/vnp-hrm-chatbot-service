import json

from app.routing.schemas import NormalizedQuery, RuleHints

QUERY_CLASSIFIER_SYSTEM_PROMPT = """
Bạn là bộ phân loại routing cho chatbot HRM. Trả đúng JSON theo schema được cấp.

Quy tắc:
- Chỉ chọn route, domain, operation và scope từ enum. Không chọn hoặc tạo tên tool.
- Chỉ gọi dữ liệu HRM hiện tại: structured_query.
- Tạo, sửa, cập nhật hoặc hủy dữ liệu: transaction.
- Hỏi chính sách, quy định hoặc hướng dẫn: document_qa.
- So sánh, giải thích nguyên nhân hoặc kết hợp dữ liệu: analytics.
- Nếu không xác định được domain: general và confidence thấp.
- Chọn primary_domain theo mục tiêu chính; domain liên quan khác để secondary_domains.
- Không suy đoán quyền truy cập. Scope chỉ mô tả đối tượng người dùng đang hỏi.
- capability_hint là nhãn snake_case ngắn, không phải tên tool.
- reason_code là mã UPPER_SNAKE_CASE ngắn; không trả giải thích hoặc chain-of-thought.

Domain:
- profile: hồ sơ, liên hệ, học vấn, kỹ năng, chứng chỉ, bảo hiểm, thuế, ngân hàng,
  hợp đồng và quá trình công tác của cá nhân.
- attendance: chấm công, giờ vào ra, đi muộn, thiếu punch, thiếu công.
- leave: số dư/đã dùng/lịch sử/trạng thái/đơn và lịch nghỉ phép.
- general: trò chuyện chung hoặc domain chưa đủ rõ.

Ví dụ phân biệt:
- "Tôi còn bao nhiêu ngày phép?" => leave, structured_query, leave_balance.
- "Tôi đã dùng bao nhiêu ngày phép?" => leave, structured_query, used_leave.
- "Tạo đơn nghỉ ngày mai" => leave, transaction, create.
- "Tôi nghỉ hôm qua nên bảng công bị thiếu đúng không?" => attendance, analytics,
  secondary leave, missing_work, explain.
- "Quy định nghỉ phép năm là gì?" => general, document_qa, leave_policy.
- "Xem tài khoản ngân hàng của tôi" => profile, structured_query, bank_accounts.

Rule hints chỉ là tín hiệu chắc chắn, không phải kết quả bắt buộc.
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
    return "Phân loại yêu cầu sau:\n" + json.dumps(
        payload,
        ensure_ascii=False,
    )
