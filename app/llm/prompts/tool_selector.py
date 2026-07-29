import json

from app.routing.schemas import ToolSelectorRequest

TOOL_SELECTOR_SYSTEM_PROMPT = """
Bạn chọn tối đa một tool cho chatbot HRM và trích xuất dữ liệu có thật trong câu hỏi.
Chỉ trả JSON theo schema.

Quy tắc bắt buộc:
- selected_tool chỉ được là một tool_name trong candidate_tools hoặc null.
- Không tạo tool, endpoint, model, field Odoo, domain hoặc ID kỹ thuật.
- Không thêm odoo_user_id, employee_id, company_id, request_id hệ thống,
  conversation_id, timezone hay API key.
- Dùng positive examples và distinctions/negative examples để hiểu mục tiêu chính,
  không chọn chỉ vì trùng từ khóa.
- Không tự tính ngày tương đối; giữ biểu thức ngày hoặc để resolver bằng code xử lý.
- Không đổi tên loại nghỉ thành leave_type_id. Có thể trả leave_type_text.
- Không suy đoán quyền xem dữ liệu người khác.
- Nếu không có candidate phù hợp: selected_tool=null.
- Nếu thiếu dữ liệu của write tool, chọn tool nhưng requires_clarification=true và
  chỉ hỏi một thông tin quan trọng nhất.
- reason_code là UPPER_SNAKE_CASE ngắn, không giải thích hoặc chain-of-thought.

Phân biệt leave:
- balance = phép còn lại; used = phép đã dùng; history = danh sách/lịch sử đơn;
  request_status = trạng thái một đơn; create/update/cancel = thao tác ghi.
Phân biệt attendance:
- daily = giờ vào/ra một ngày; history = từng bản ghi; monthly_summary = tổng kỳ;
  late_summary = đi muộn; missing_punch = quên chấm vào/ra.
Phân biệt profile:
- summary = hồ sơ tổng quan; employment = chức vụ/phòng ban/quản lý/quá trình làm.
""".strip()


def build_tool_selector_prompt(request: ToolSelectorRequest) -> str:
    compact = {
        "query": request.normalized_query,
        "route": request.classification.route.value,
        "intent": (
            request.classification.intent.value
            if request.classification.intent
            else None
        ),
        "operation": request.classification.operation.value,
        "scope": request.classification.scope.value,
        "candidate_tools": [
            {
                "name": candidate.tool_name,
                "purpose": candidate.description,
                "supported_intent": candidate.capability,
                "required_arguments": candidate.required_arguments,
                "optional_arguments": candidate.optional_arguments,
            }
            for candidate in request.candidates[:3]
        ],
    }
    return "Chọn tool cho request sau:\n" + json.dumps(
        compact,
        ensure_ascii=False,
    )
