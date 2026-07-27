from app.tools.definitions import (
    Domain,
    HttpMethod,
    NoArguments,
    Operation,
    RiskLevel,
    RouteType,
    ToolDefinition,
)

_BASE = "/api/hrm-chatbot/v1/profile/current"


def _profile_tool(
    *,
    name: str,
    capability: str,
    description: str,
    endpoint: str,
    examples: tuple[str, ...],
    negative_examples: tuple[str, ...],
    sensitive: bool = False,
) -> ToolDefinition:
    return ToolDefinition(
        name=name,
        domain=Domain.PROFILE,
        capability=capability,
        operation=Operation.GET,
        route_type=RouteType.QUERY,
        risk_level=(
            RiskLevel.SENSITIVE_READ if sensitive else RiskLevel.READ
        ),
        description=description,
        endpoint=f"{_BASE}/{endpoint}",
        http_method=HttpMethod.GET,
        argument_schema=NoArguments,
        examples=examples,
        negative_examples=negative_examples,
        sensitive=sensitive,
    )


PROFILE_TOOLS = (
    _profile_tool(
        name="profile_get_summary",
        capability="profile.summary",
        description="Lấy thông tin hồ sơ nhân sự tổng quan của chính người dùng.",
        endpoint="summary",
        examples=(
            "Cho tôi xem hồ sơ nhân sự tổng quan.",
            "Thông tin cơ bản trong hồ sơ của tôi là gì?",
            "Tóm tắt hồ sơ công việc hiện tại của tôi.",
            "Hiển thị mã nhân viên, chức danh và đơn vị của tôi.",
            "Tôi muốn kiểm tra thông tin nhân viên khái quát.",
        ),
        negative_examples=(
            "Số tài khoản nhận lương của tôi là gì?",
            "Các hợp đồng lao động của tôi còn hiệu lực không?",
            "Tôi có những chứng chỉ chuyên môn nào?",
        ),
    ),
    _profile_tool(
        name="profile_get_employment",
        capability="profile.employment",
        description="Lấy thông tin vị trí, đơn vị và quá trình vào làm hiện tại.",
        endpoint="employment",
        examples=(
            "Thông tin công tác hiện tại của tôi.",
            "Tôi đang giữ vị trí nào trong đơn vị?",
            "Ngày tôi vào đơn vị là khi nào?",
            "Cho xem phòng ban, chức danh và quản lý trực tiếp.",
            "Trạng thái làm việc hiện tại của tôi ra sao?",
        ),
        negative_examples=(
            "Lịch sử điều chuyển công tác của tôi.",
            "Cho xem nội dung các hợp đồng lao động.",
            "Email và số điện thoại cá nhân của tôi.",
        ),
    ),
    _profile_tool(
        name="profile_get_contact",
        capability="profile.contact",
        description="Lấy email và số điện thoại liên hệ của chính người dùng.",
        endpoint="contact",
        examples=(
            "Thông tin liên hệ của tôi đang lưu thế nào?",
            "Cho xem email công việc và số điện thoại của tôi.",
            "Số di động trong hồ sơ của tôi là số nào?",
            "Kiểm tra email cá nhân tôi đã khai báo.",
            "Hiển thị các số điện thoại liên hệ của tôi.",
        ),
        negative_examples=(
            "Thông tin ngân hàng của tôi.",
            "Tôi đang thuộc phòng ban nào?",
            "Cho xem mã số thuế cá nhân.",
        ),
    ),
    _profile_tool(
        name="profile_get_history",
        capability="profile.history",
        description="Lấy lịch sử thay đổi công tác của chính người dùng.",
        endpoint="history",
        examples=(
            "Cho tôi xem lịch sử công tác.",
            "Tôi từng chuyển qua những đơn vị nào?",
            "Các lần thay đổi chức vụ của tôi.",
            "Quá trình điều chuyển phòng ban trước đây.",
            "Lịch sử vị trí làm việc của tôi ra sao?",
        ),
        negative_examples=(
            "Vị trí công tác hiện tại của tôi là gì?",
            "Lịch sử nghỉ phép năm nay.",
            "Các hợp đồng lao động đã ký.",
        ),
    ),
    _profile_tool(
        name="profile_get_education",
        capability="profile.education",
        description="Lấy thông tin quá trình đào tạo và học vấn.",
        endpoint="education",
        examples=(
            "Cho xem thông tin học vấn của tôi.",
            "Tôi đã khai báo những bằng cấp đào tạo nào?",
            "Quá trình học tập trong hồ sơ nhân sự.",
            "Trình độ chuyên môn của tôi đang được lưu ra sao?",
            "Danh sách trường và ngành tôi đã học.",
        ),
        negative_examples=(
            "Tôi có chứng chỉ nghề nghiệp nào?",
            "Những kỹ năng của tôi trong hồ sơ.",
            "Thông tin vị trí công tác hiện tại.",
        ),
    ),
    _profile_tool(
        name="profile_get_certificates",
        capability="profile.certificates",
        description="Lấy danh sách chứng chỉ của chính người dùng.",
        endpoint="certificates",
        examples=(
            "Tôi có những chứng chỉ nào?",
            "Danh sách chứng chỉ chuyên môn trong hồ sơ.",
            "Chứng chỉ ngoại ngữ của tôi đã được ghi nhận chưa?",
            "Cho xem ngày hết hạn các chứng nhận của tôi.",
            "Kiểm tra các chứng chỉ nghề nghiệp đã khai báo.",
        ),
        negative_examples=(
            "Trình độ học vấn và bằng đại học của tôi.",
            "Các kỹ năng chuyên môn của tôi.",
            "Hợp đồng lao động hiện tại hết hạn khi nào?",
        ),
    ),
    _profile_tool(
        name="profile_get_skills",
        capability="profile.skills",
        description="Lấy danh sách kỹ năng trong hồ sơ nhân sự.",
        endpoint="skills",
        examples=(
            "Hồ sơ của tôi có những kỹ năng nào?",
            "Cho xem danh sách kỹ năng chuyên môn.",
            "Mức độ thành thạo các kỹ năng của tôi.",
            "Tôi đã khai báo năng lực nào trong hồ sơ?",
            "Kiểm tra thông tin kỹ năng nghề nghiệp.",
        ),
        negative_examples=(
            "Danh sách chứng chỉ của tôi.",
            "Thông tin bằng cấp và trường đào tạo.",
            "Tóm tắt vị trí công tác của tôi.",
        ),
    ),
    _profile_tool(
        name="profile_get_insurance",
        capability="profile.insurance",
        description="Lấy thông tin bảo hiểm nhạy cảm của chính người dùng.",
        endpoint="insurance",
        examples=(
            "Thông tin bảo hiểm xã hội của tôi.",
            "Cho xem mã số bảo hiểm đã đăng ký.",
            "Nơi đăng ký khám chữa bệnh ban đầu của tôi.",
            "Kiểm tra dữ liệu bảo hiểm y tế trong hồ sơ.",
            "Tôi muốn xem thông tin tham gia bảo hiểm.",
        ),
        negative_examples=(
            "Mã số thuế cá nhân của tôi.",
            "Tài khoản ngân hàng nhận lương.",
            "Thông tin liên hệ trong hồ sơ.",
        ),
        sensitive=True,
    ),
    _profile_tool(
        name="profile_get_tax",
        capability="profile.tax",
        description="Lấy thông tin thuế cá nhân nhạy cảm của chính người dùng.",
        endpoint="tax",
        examples=(
            "Mã số thuế cá nhân của tôi là gì?",
            "Cho xem thông tin đăng ký thuế của tôi.",
            "Dữ liệu người phụ thuộc tính thuế của tôi.",
            "Kiểm tra hồ sơ thuế thu nhập cá nhân.",
            "Thông tin cơ quan thuế của tôi đang lưu thế nào?",
        ),
        negative_examples=(
            "Mã số bảo hiểm xã hội của tôi.",
            "Số tài khoản ngân hàng nhận lương.",
            "Tổng số ngày phép còn lại.",
        ),
        sensitive=True,
    ),
    _profile_tool(
        name="profile_get_bank_accounts",
        capability="profile.bank_accounts",
        description="Lấy danh sách tài khoản ngân hàng nhạy cảm của người dùng.",
        endpoint="bank-accounts",
        examples=(
            "Tài khoản ngân hàng nhận lương của tôi.",
            "Cho xem số tài khoản tôi đã đăng ký.",
            "Ngân hàng nào đang được lưu trong hồ sơ của tôi?",
            "Kiểm tra thông tin chi nhánh tài khoản cá nhân.",
            "Danh sách tài khoản thanh toán của tôi.",
        ),
        negative_examples=(
            "Mã số thuế cá nhân là gì?",
            "Thông tin bảo hiểm y tế của tôi.",
            "Email công việc đang dùng.",
        ),
        sensitive=True,
    ),
    _profile_tool(
        name="profile_get_contracts",
        capability="profile.contracts",
        description="Lấy danh sách và trạng thái hợp đồng lao động.",
        endpoint="contracts",
        examples=(
            "Cho xem các hợp đồng lao động của tôi.",
            "Hợp đồng hiện tại của tôi hết hạn ngày nào?",
            "Danh sách hợp đồng tôi đã ký với công ty.",
            "Tình trạng hợp đồng làm việc hiện tại.",
            "Hợp đồng của tôi còn bao nhiêu ngày hiệu lực?",
        ),
        negative_examples=(
            "Ngày tôi chính thức vào đơn vị.",
            "Lịch sử thay đổi chức danh của tôi.",
            "Tôi còn bao nhiêu ngày phép?",
        ),
    ),
)
