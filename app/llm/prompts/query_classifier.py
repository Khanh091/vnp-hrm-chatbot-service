import json

from app.routing.schemas import NormalizedQuery, RuleHints

QUERY_CLASSIFIER_SYSTEM_PROMPT = """
Bạn phân loại yêu cầu tiếng Việt cho chatbot HRM. Chỉ trả JSON đúng schema.

Ý nghĩa các trục:
- intent xác định nhóm dữ liệu nghiệp vụ, không mã hóa thao tác vào intent.
- operation là read/create/update/delete/cancel/none.
- route là knowledge/data_query/task/general/unsupported/unsafe.
- domain là profile/attendance/leave/directory/reporting/general hoặc null.
- scope là self/named_employee/department/company/general/unknown.

Quy tắc thao tác:
- thêm/tạo/bổ sung/khai thêm thường là create.
- sửa/đổi/cập nhật/chỉnh lại/thay thường là update.
- xóa/bỏ/gỡ thường là delete; tuyệt đối không đổi "xóa" thành cancel.
- cancel chỉ dùng để hủy/rút workflow hoặc chứng từ, ví dụ đơn nghỉ.
- profile.* + read: domain=profile, route=data_query.
- profile.* + create/update/delete: domain=profile, route=task, scope=self.
- Giữ intent theo resource nghiệp vụ: profile.certificates với operation riêng,
  không tạo intent profile.certificates.create/update/delete.

Ràng buộc an toàn:
- Không kết luận quyền thao tác; registry sẽ quyết định quyền.
- Không tạo field, resource, technical ID, model, endpoint hay capability.
- Chỉ chọn intent có trong JSON Schema, không tạo intent mới.
- Nếu người dùng chỉ nói một section hồ sơ rộng, chọn profile intent gần nhất
  hoặc profile.summary; schema resolver sẽ hỏi tiếp.
- Rule hints chỉ là tín hiệu. Tín hiệu write chỉ gợi ý operation, không đủ để
  tự suy ra field/resource khi danh từ không độc nhất.
- reason_code là mã UPPER_SNAKE_CASE ngắn.

Ranh giới quan trọng:
- "hủy đơn nghỉ" => leave.cancel + cancel.
- "xóa chứng chỉ" => profile.certificates + delete.
- "đổi phòng ban" => profile.department + update; không quyết định được sửa.
- "thêm người thân" => profile.family_relations + create.
- "sửa ngày cấp TOEIC" => profile.certificates + update.

Nhóm profile thường dùng: thông tin chung => profile.summary; điện thoại/email/
liên hệ => profile.contact; phòng ban => profile.department; địa chỉ/quê quán =>
profile.address; chứng chỉ => profile.certificates; người thân =>
profile.family_relations; sức khỏe/tiêm chủng => profile.health. Với các nhóm
khác, chọn enum profile.* gần nhất theo toàn bộ câu.

Phân biệt rõ các intent dễ nhầm:
- profile.summary/profile.basic là thông tin hồ sơ cơ bản và tổng quan như họ tên,
  tên gọi khác, mã nhân viên, chức danh và đơn vị.
- profile.identity là giấy tờ và thuộc tính định danh như CCCD/CMND/hộ chiếu,
  ngày-nơi cấp, quốc tịch, dân tộc, tôn giáo và tình trạng hôn nhân. Từ "identity"
  ở đây không có nghĩa là họ tên của nhân viên.
- Câu hỏi chỉ hỏi tên hoặc họ tên của chính người dùng phải thuộc nhóm thông tin
  cơ bản/tổng quan, không thuộc profile.identity.

Dữ liệu hiện tại là data_query/read; chính sách là knowledge/read; chào hỏi là
general/none; ngoài HRM là unsupported. Không suy đoán quyền từ scope.
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
        "Phân loại yêu cầu sau. Trả đủ field theo schema, không giải thích:\n"
        + json.dumps(payload, ensure_ascii=False)
    )
