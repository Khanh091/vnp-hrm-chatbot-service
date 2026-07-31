from app.routing.taxonomy import Intent
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
    intents: frozenset[Intent] = frozenset(),
    sensitive: bool = False,
    base: str = _BASE,
) -> ToolDefinition:
    return ToolDefinition(
        name=name,
        domain=Domain.PROFILE,
        capability=capability,
        intents=intents,
        operation=Operation.GET,
        route_type=RouteType.QUERY,
        risk_level=(
            RiskLevel.SENSITIVE_READ if sensitive else RiskLevel.READ
        ),
        description=description,
        endpoint=f"{base}/{endpoint}",
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
        intents=frozenset(
            {
                Intent.PROFILE_BASIC,
                Intent.PROFILE_SUMMARY,
                Intent.PROFILE_EMPLOYEE_CODE,
            }
        ),
        description=(
            "Lấy hồ sơ nhân sự tổng quan của chính người dùng, gồm họ tên, "
            "mã nhân viên/mã nhân sự, ngày sinh nếu có và thông tin cá nhân cơ bản."
        ),
        endpoint="summary",
        examples=(
            "Cho tôi xem hồ sơ nhân sự tổng quan.",
            "Thông tin cơ bản trong hồ sơ của tôi là gì?",
            "Tóm tắt hồ sơ công việc hiện tại của tôi.",
            "Hiển thị mã nhân viên, chức danh và đơn vị của tôi.",
            "Tôi muốn kiểm tra thông tin nhân viên khái quát.",
            "Tên của tôi là gì?",
            "Họ tên đầy đủ của tôi là gì?",
            "Mã nhân viên của tôi là gì?",
            "Mã nhân sự của tôi là gì?",
            "Ngày sinh của tôi là gì?",
            "Thông tin cá nhân của tôi.",
            "ten cua toi la gi",
            "ma nhan vien cua toi",
            "ma nhan su cua toi",
            "thong tin ca nhan cua toi",
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
        intents=frozenset(
            {
                Intent.PROFILE_EMPLOYMENT,
                Intent.PROFILE_JOB_TITLE,
                Intent.PROFILE_DEPARTMENT,
                Intent.PROFILE_WORK_UNIT,
                Intent.PROFILE_MANAGER,
            }
        ),
        description=(
            "Lấy thông tin công tác hiện tại: đơn vị, công ty, phòng ban, chức danh, "
            "vị trí công việc, loại nhân sự, trạng thái làm việc và quản lý trực tiếp."
        ),
        endpoint="employment",
        examples=(
            "Thông tin công tác hiện tại của tôi.",
            "Tôi đang giữ vị trí nào trong đơn vị?",
            "Ngày tôi vào đơn vị là khi nào?",
            "Cho xem phòng ban, chức danh và quản lý trực tiếp.",
            "Trạng thái làm việc hiện tại của tôi ra sao?",
            "Đơn vị công tác của tôi là gì?",
            "Công ty của tôi là gì?",
            "Phòng ban của tôi là gì?",
            "Tôi thuộc phòng nào?",
            "Chức danh công việc của tôi là gì?",
            "Vị trí làm việc của tôi là gì?",
            "Loại nhân sự của tôi là gì?",
            "Quản lý trực tiếp của tôi là ai?",
            "Sếp trực tiếp của tôi là ai?",
            "don vi cong tac cua toi",
            "phong ban cua toi",
            "chuc danh cong viec cua toi",
            "quan ly truc tiep cua toi",
            "Tôi làm ở đâu?",
            "Nơi làm việc hiện tại của tôi.",
            "Cơ quan của tôi là đơn vị nào?",
        ),
        negative_examples=(
            "Lịch sử điều chuyển công tác của tôi.",
            "Cho xem nội dung các hợp đồng lao động.",
            "Email và số điện thoại cá nhân của tôi.",
            "Danh sách nhân viên phòng Kế toán.",
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
            "Email của tôi là gì?",
            "Email công việc của tôi.",
            "Số điện thoại của tôi là gì?",
            "email cua toi",
            "so dien thoai cua toi",
            "thong tin lien he cua toi",
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
        intents=frozenset(
            {Intent.PROFILE_HISTORY, Intent.PROFILE_WORK_HISTORY}
        ),
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
            "Trình độ đào tạo của tôi.",
            "Trình độ học vấn của tôi.",
            "Bằng cấp của tôi.",
            "trinh do dao tao cua toi",
            "trinh do hoc van cua toi",
            "bang cap cua toi",
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
        intents=frozenset(
            {Intent.PROFILE_CONTRACTS, Intent.PROFILE_CONTRACT_EXPIRY}
        ),
        description="Lấy danh sách và trạng thái hợp đồng lao động.",
        endpoint="contracts",
        examples=(
            "Cho xem các hợp đồng lao động của tôi.",
            "Hợp đồng hiện tại của tôi hết hạn ngày nào?",
            "Danh sách hợp đồng tôi đã ký với công ty.",
            "Tình trạng hợp đồng làm việc hiện tại.",
            "Hợp đồng của tôi còn bao nhiêu ngày hiệu lực?",
            "Hợp đồng hiện tại của tôi.",
            "Ngày hết hạn hợp đồng của tôi.",
            "Hợp đồng của tôi hết hạn khi nào?",
            "Lịch sử hợp đồng của tôi.",
            "hop dong hien tai cua toi",
            "ngay het han hop dong cua toi",
            "lich su hop dong cua toi",
        ),
        negative_examples=(
            "Ngày tôi chính thức vào đơn vị.",
            "Lịch sử thay đổi chức danh của tôi.",
            "Tôi còn bao nhiêu ngày phép?",
        ),
    ),
    _profile_tool(
        name="profile_get_identity",
        capability=Intent.PROFILE_IDENTITY.value,
        intents=frozenset({Intent.PROFILE_IDENTITY}),
        description=(
            "Tra cứu nhóm thông tin định danh cá nhân gồm căn cước, ngày/nơi "
            "cấp, quốc tịch, dân tộc, tôn giáo, giới tính và hôn nhân."
        ),
        endpoint="identity",
        base="/api/v1/hrm/profile/current",
        sensitive=True,
        examples=(
            "Dân tộc của tôi đang được lưu là gì?",
            "CCCD của tôi được cấp ngày nào?",
            "Nơi cấp căn cước của tôi.",
            "Quốc tịch và tôn giáo của tôi.",
            "Tình trạng hôn nhân trong hồ sơ của tôi.",
            "so can cuoc cua toi",
            "dan toc cua toi",
        ),
        negative_examples=(
            "Địa chỉ thường trú của tôi.",
            "Email công việc của tôi.",
            "Nhân viên nào có chứng chỉ AWS?",
        ),
    ),
    _profile_tool(
        name="profile_get_addresses",
        capability=Intent.PROFILE_ADDRESS.value,
        intents=frozenset({Intent.PROFILE_ADDRESS}),
        description=(
            "Tra cứu nhóm địa chỉ gồm hộ khẩu, thường trú, nơi ở hiện tại, "
            "quê quán và nơi sinh của chính người dùng."
        ),
        endpoint="addresses",
        base="/api/v1/hrm/profile/current",
        sensitive=True,
        examples=(
            "Nơi ở hiện tại của tôi là đâu?",
            "Địa chỉ thường trú của tôi.",
            "Hộ khẩu của tôi đang lưu thế nào?",
            "Quê quán và nơi sinh của tôi.",
            "Tôi đang sống ở đâu theo hồ sơ?",
            "noi o hien tai cua toi",
            "dia chi thuong tru cua toi",
        ),
        negative_examples=(
            "Đơn vị công tác của tôi.",
            "Nơi cấp căn cước của tôi.",
            "Danh sách nhân viên phòng Kế toán.",
        ),
    ),
    _profile_tool(
        name="profile_get_recruitment",
        capability=Intent.PROFILE_RECRUITMENT.value,
        intents=frozenset({Intent.PROFILE_RECRUITMENT}),
        description=(
            "Tra cứu thông tin tuyển dụng: ngày và hình thức tuyển dụng, ngày "
            "vào công ty/TCT/đơn vị, cơ quan tuyển dụng và sở trường công tác."
        ),
        endpoint="recruitment",
        base="/api/v1/hrm/profile/current",
        examples=(
            "Tôi được tuyển dụng ngày nào?",
            "Hình thức tuyển dụng của tôi.",
            "Tôi vào TCT từ ngày nào?",
            "Ngày tôi vào đơn vị hiện tại.",
            "Cơ quan nào tuyển dụng tôi?",
            "ngay vao tct cua toi",
            "hinh thuc tuyen dung cua toi",
        ),
        negative_examples=(
            "Hợp đồng của tôi hết hạn khi nào?",
            "Chức danh hiện tại của tôi.",
            "Lịch sử điều chuyển của tôi.",
        ),
    ),
    _profile_tool(
        name="profile_get_training_history",
        capability=Intent.PROFILE_TRAINING_HISTORY.value,
        intents=frozenset({Intent.PROFILE_TRAINING_HISTORY}),
        description=(
            "Tra cứu lịch sử đào tạo bồi dưỡng, khóa học và cam kết đào tạo "
            "của chính người dùng."
        ),
        endpoint="training-history",
        base="/api/v1/hrm/profile/current",
        examples=(
            "Lịch sử đào tạo của tôi.",
            "Tôi đã tham gia những khóa học nào?",
            "Quá trình đào tạo bồi dưỡng của tôi.",
            "Các cam kết đào tạo của tôi.",
            "Cho xem những đợt bồi dưỡng đã tham gia.",
            "lich su dao tao cua toi",
            "khoa hoc cua toi",
        ),
        negative_examples=(
            "Trình độ học vấn của tôi.",
            "Chứng chỉ nghề nghiệp của tôi.",
            "Lịch sử bổ nhiệm của tôi.",
        ),
    ),
    _profile_tool(
        name="profile_get_appointment_history",
        capability=Intent.PROFILE_APPOINTMENT_HISTORY.value,
        intents=frozenset({Intent.PROFILE_APPOINTMENT_HISTORY}),
        description=(
            "Tra cứu lịch sử bổ nhiệm, quá trình giữ chức và các quyết định "
            "bổ nhiệm của chính người dùng."
        ),
        endpoint="appointment-history",
        base="/api/v1/hrm/profile/current",
        examples=(
            "Quá trình bổ nhiệm của tôi.",
            "Lịch sử bổ nhiệm của tôi.",
            "Tôi từng giữ những chức vụ nào?",
            "Các quyết định bổ nhiệm của tôi.",
            "Quá trình giữ chức trong hồ sơ.",
            "lich su bo nhiem cua toi",
            "qua trinh giu chuc cua toi",
        ),
        negative_examples=(
            "Chức danh hiện tại của tôi.",
            "Lịch sử điều chuyển của tôi.",
            "Ngày tuyển dụng của tôi.",
        ),
    ),
    _profile_tool(
        name="profile_get_transfer_history",
        capability=Intent.PROFILE_TRANSFER_HISTORY.value,
        intents=frozenset({Intent.PROFILE_TRANSFER_HISTORY}),
        description=(
            "Tra cứu lịch sử điều chuyển, luân chuyển và chuyển đơn vị của "
            "chính người dùng."
        ),
        endpoint="transfer-history",
        base="/api/v1/hrm/profile/current",
        examples=(
            "Lịch sử điều chuyển của tôi.",
            "Tôi từng luân chuyển qua đâu?",
            "Các lần chuyển đơn vị của tôi.",
            "Quá trình điều chuyển công tác.",
            "Tôi đã chuyển phòng ban những lần nào?",
            "lich su dieu chuyen cua toi",
            "chuyen don vi cua toi",
        ),
        negative_examples=(
            "Đơn vị hiện tại của tôi.",
            "Lịch sử bổ nhiệm của tôi.",
            "Quá trình đào tạo của tôi.",
        ),
    ),
    _profile_tool(
        name="profile_get_family_relations",
        capability=Intent.PROFILE_FAMILY_RELATIONS.value,
        intents=frozenset({Intent.PROFILE_FAMILY_RELATIONS}),
        description=(
            "Tra cứu nhóm quan hệ gia đình, người thân, vợ chồng, con cái và "
            "thân nhân của chính người dùng."
        ),
        endpoint="family-relations",
        base="/api/v1/hrm/profile/current",
        sensitive=True,
        examples=(
            "Thông tin người thân của tôi.",
            "Quan hệ gia đình của tôi.",
            "Hồ sơ vợ chồng của tôi.",
            "Thông tin con cái trong hồ sơ.",
            "Danh sách thân nhân của tôi.",
            "nguoi than cua toi",
        ),
        negative_examples=(
            "Tình trạng hôn nhân của tôi.",
            "Sở thích của tôi.",
            "Danh sách nhân viên phòng Kế toán.",
        ),
    ),
    _profile_tool(
        name="profile_get_rewards",
        capability=Intent.PROFILE_REWARDS.value,
        intents=frozenset({Intent.PROFILE_REWARDS}),
        description=(
            "Tra cứu lịch sử khen thưởng, thành tích, bằng khen và quyết định "
            "khen thưởng của chính người dùng."
        ),
        endpoint="rewards",
        base="/api/v1/hrm/profile/current",
        sensitive=True,
        examples=(
            "Tôi đã được khen thưởng gì?",
            "Các thành tích của tôi.",
            "Bằng khen trong hồ sơ của tôi.",
            "Lịch sử khen thưởng của tôi.",
            "Các quyết định khen thưởng dành cho tôi.",
            "khen thuong cua toi",
        ),
        negative_examples=(
            "Lịch sử kỷ luật của tôi.",
            "Kết quả đánh giá của tôi.",
            "Chứng chỉ của tôi.",
        ),
    ),
    _profile_tool(
        name="profile_get_disciplines",
        capability=Intent.PROFILE_DISCIPLINES.value,
        intents=frozenset({Intent.PROFILE_DISCIPLINES}),
        description=(
            "Tra cứu lịch sử kỷ luật, hình thức xử lý và quyết định kỷ luật "
            "của chính người dùng."
        ),
        endpoint="disciplines",
        base="/api/v1/hrm/profile/current",
        sensitive=True,
        examples=(
            "Lịch sử kỷ luật của tôi.",
            "Tôi từng bị xử lý kỷ luật chưa?",
            "Các quyết định kỷ luật của tôi.",
            "Hình thức kỷ luật trong hồ sơ.",
            "Cho xem quá trình xử lý kỷ luật của tôi.",
            "ky luat cua toi",
        ),
        negative_examples=(
            "Tôi đã được khen thưởng gì?",
            "Kết quả đánh giá gần nhất.",
            "Lịch sử điều chuyển của tôi.",
        ),
    ),
    _profile_tool(
        name="profile_get_evaluations",
        capability=Intent.PROFILE_EVALUATIONS.value,
        intents=frozenset({Intent.PROFILE_EVALUATIONS}),
        description=(
            "Tra cứu kết quả đánh giá nhân sự, xếp loại và nhận xét của đơn vị "
            "đối với chính người dùng."
        ),
        endpoint="evaluations",
        base="/api/v1/hrm/profile/current",
        sensitive=True,
        examples=(
            "Kết quả đánh giá gần nhất của tôi.",
            "Tôi được xếp loại thế nào?",
            "Lịch sử đánh giá nhân sự của tôi.",
            "Nhận xét của đơn vị về tôi.",
            "Các kết quả đánh giá qua từng năm.",
            "ket qua danh gia cua toi",
        ),
        negative_examples=(
            "Lịch sử khen thưởng của tôi.",
            "Quá trình bổ nhiệm của tôi.",
            "Mục tiêu cá nhân của tôi.",
        ),
    ),
    _profile_tool(
        name="profile_get_party_union",
        capability=Intent.PROFILE_PARTY_UNION.value,
        intents=frozenset({Intent.PROFILE_PARTY_UNION}),
        description=(
            "Tra cứu thông tin Đảng, Đoàn và lịch sử sinh hoạt Đoàn của chính "
            "người dùng."
        ),
        endpoint="party-union",
        base="/api/v1/hrm/profile/current",
        sensitive=True,
        examples=(
            "Tôi có phải Đảng viên không?",
            "Tôi vào Đảng ngày nào?",
            "Ngày vào Đoàn của tôi.",
            "Tôi có phải Đoàn viên không?",
            "Lịch sử sinh hoạt Đoàn của tôi.",
            "ngay vao doan cua toi",
        ),
        negative_examples=(
            "Tôn giáo của tôi.",
            "Sở thích của tôi.",
            "Quá trình bổ nhiệm của tôi.",
        ),
    ),
    _profile_tool(
        name="profile_get_preferences",
        capability=Intent.PROFILE_PREFERENCES.value,
        intents=frozenset({Intent.PROFILE_PREFERENCES}),
        description=(
            "Tra cứu mục tiêu cá nhân, sở thích, điểm mạnh và điểm yếu của "
            "chính người dùng."
        ),
        endpoint="preferences",
        base="/api/v1/hrm/profile/current",
        sensitive=True,
        examples=(
            "Sở thích của tôi.",
            "Mục tiêu cá nhân của tôi là gì?",
            "Điểm mạnh trong hồ sơ của tôi.",
            "Điểm yếu của tôi đang được lưu thế nào?",
            "Thông tin sở trường cá nhân của tôi.",
            "so thich cua toi",
        ),
        negative_examples=(
            "Sở trường công tác khi tuyển dụng.",
            "Kết quả đánh giá của tôi.",
            "Kỹ năng chuyên môn của tôi.",
        ),
    ),
)
