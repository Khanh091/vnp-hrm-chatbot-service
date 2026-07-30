from app.routing.taxonomy import Intent, SubjectType
from app.tools.definitions import (
    DepartmentEmployeesArguments,
    Domain,
    EmployeeCertificateSearchArguments,
    EmployeeSearchArguments,
    EmployeeSubjectArguments,
    HttpMethod,
    Operation,
    RiskLevel,
    RouteType,
    SubjectScope,
    ToolDefinition,
)

_BASE = "/api/v1/hrm"
_EMPLOYEE_SUBJECT = (SubjectScope.NAMED_EMPLOYEE,)


def _named_profile_tool(
    *,
    name: str,
    capability: Intent,
    intents: frozenset[Intent],
    endpoint: str,
    description: str,
    examples: tuple[str, ...],
    negative_examples: tuple[str, ...],
    sensitive: bool = False,
) -> ToolDefinition:
    return ToolDefinition(
        name=name,
        domain=Domain.DIRECTORY,
        capability=capability.value,
        intent=capability,
        intents=intents,
        operation=Operation.GET,
        route_type=RouteType.QUERY,
        risk_level=(
            RiskLevel.SENSITIVE_READ if sensitive else RiskLevel.READ
        ),
        description=description,
        endpoint=f"{_BASE}/employees/{{employee_id}}/{endpoint}",
        http_method=HttpMethod.GET,
        argument_schema=EmployeeSubjectArguments,
        path_arguments=("employee_id",),
        examples=examples,
        negative_examples=negative_examples,
        supported_scopes=_EMPLOYEE_SUBJECT,
        supported_subject_types=(SubjectType.EMPLOYEE,),
        sensitive=sensitive,
        version="1.0",
    )


DIRECTORY_TOOLS = (
    ToolDefinition(
        name="employee_find_by_certificate",
        domain=Domain.DIRECTORY,
        capability=Intent.DIRECTORY_EMPLOYEE_BY_CERTIFICATE.value,
        intent=Intent.DIRECTORY_EMPLOYEE_BY_CERTIFICATE,
        intents=frozenset({Intent.DIRECTORY_EMPLOYEE_BY_CERTIFICATE}),
        operation=Operation.LIST,
        route_type=RouteType.QUERY,
        risk_level=RiskLevel.READ,
        description=(
            "Tìm nhân viên sở hữu chứng chỉ hoặc chứng nhận theo tên, loại và "
            "ngày hiệu lực; có thể giới hạn theo phòng ban hoặc công ty đã resolve."
        ),
        endpoint=f"{_BASE}/employees/search-by-certificate",
        http_method=HttpMethod.POST,
        argument_schema=EmployeeCertificateSearchArguments,
        examples=(
            "Nhân viên nào có chứng chỉ AWS?",
            "Ai có chứng nhận quản lý dự án PMP?",
            "Tìm người có chứng chỉ an toàn lao động.",
            "Người sở hữu chứng chỉ TOEIC trong công ty.",
            "Tìm nhân viên phòng Kế toán có chứng chỉ hành nghề.",
            "nhan vien nao co chung chi aws",
        ),
        negative_examples=(
            "Chứng chỉ của tôi.",
            "Chứng chỉ của Lò Văn Định.",
            "Trình độ học vấn của tôi.",
            "Danh sách nhân viên phòng Kế toán.",
        ),
        supported_scopes=(
            SubjectScope.COMPANY,
            SubjectScope.DEPARTMENT,
        ),
        supported_subject_types=(
            SubjectType.COMPANY,
            SubjectType.DEPARTMENT,
        ),
        required_actor_capability="directory.employee_by_certificate",
        version="1.0",
    ),
    ToolDefinition(
        name="employee_search",
        domain=Domain.DIRECTORY,
        capability=Intent.DIRECTORY_EMPLOYEE_SEARCH.value,
        intents=frozenset({Intent.DIRECTORY_EMPLOYEE_SEARCH}),
        operation=Operation.GET,
        route_type=RouteType.QUERY,
        risk_level=RiskLevel.READ,
        description=(
            "Tìm nhân viên theo tên, mã nhân sự hoặc phòng ban bằng endpoint "
            "directory allowlist; không truy cập ORM tùy ý."
        ),
        endpoint=f"{_BASE}/employees/search",
        http_method=HttpMethod.POST,
        argument_schema=EmployeeSearchArguments,
        examples=(
            "Tìm nhân viên tên Lò Văn Định.",
            "Tra cứu nhân viên theo mã nhân sự 00234086.",
            "Tìm người có tên Nguyễn Văn An.",
            "Tìm hồ sơ nhân viên theo mã cán bộ.",
            "Search nhân viên trong một phòng đã chọn.",
            "tim nhan vien theo ma nhan su",
        ),
        negative_examples=(
            "Phòng ban của tôi là gì?",
            "Danh sách nhân viên phòng Kế toán.",
            "Nhân viên đó đang giữ chức danh gì?",
        ),
        supported_scopes=_EMPLOYEE_SUBJECT,
        supported_subject_types=(SubjectType.EMPLOYEE,),
        version="1.0",
    ),
    ToolDefinition(
        name="department_list_employees",
        domain=Domain.DIRECTORY,
        capability=Intent.DIRECTORY_DEPARTMENT_EMPLOYEES.value,
        intents=frozenset({Intent.DIRECTORY_DEPARTMENT_EMPLOYEES}),
        operation=Operation.LIST,
        route_type=RouteType.QUERY,
        risk_level=RiskLevel.READ,
        description=(
            "Liệt kê nhân viên thuộc một phòng ban đã được resolve; hỗ trợ "
            "lọc trạng thái làm việc, loại nhân sự và chức danh."
        ),
        endpoint=f"{_BASE}/departments/{{department_id}}/employees",
        http_method=HttpMethod.GET,
        argument_schema=DepartmentEmployeesArguments,
        path_arguments=("department_id",),
        examples=(
            "Cho tôi danh sách nhân viên phòng Kế toán.",
            "Phòng Kinh doanh hiện có những nhân viên nào?",
            "Liệt kê người đang làm tại đơn vị này.",
            "Xem nhân sự thuộc phòng đã chọn.",
            "Danh sách cán bộ của cơ quan đó.",
            "danh sach nhan vien phong ke toan",
        ),
        negative_examples=(
            "Lò Văn Định ở cơ quan nào?",
            "Nhân viên mã 00234086 thuộc phòng nào?",
            "Tìm phòng ban có tên Kế toán.",
        ),
        supported_scopes=(SubjectScope.DEPARTMENT,),
        supported_subject_types=(SubjectType.DEPARTMENT,),
        version="1.0",
    ),
    _named_profile_tool(
        name="employee_get_basic",
        capability=Intent.DIRECTORY_EMPLOYEE_PROFILE,
        intents=frozenset(
            {
                Intent.DIRECTORY_EMPLOYEE_PROFILE,
                Intent.PROFILE_BASIC,
                Intent.PROFILE_SUMMARY,
                Intent.PROFILE_EMPLOYEE_CODE,
            }
        ),
        endpoint="basic",
        description="Lấy thông tin cơ bản của một nhân viên đã được resolve.",
        examples=(
            "Cho xem hồ sơ cơ bản của nhân viên đó.",
            "Mã nhân sự của Lò Văn Định là gì?",
            "Thông tin cá nhân của nhân viên mã 00234086.",
            "Họ tên đầy đủ của người vừa tìm.",
            "Xem hồ sơ tổng quan của cán bộ này.",
        ),
        negative_examples=(
            "Lò Văn Định thuộc phòng nào?",
            "Email của nhân viên đó.",
            "Danh sách nhân viên phòng Kế toán.",
        ),
    ),
    _named_profile_tool(
        name="employee_get_employment",
        capability=Intent.DIRECTORY_EMPLOYEE_DEPARTMENT,
        intents=frozenset(
            {
                Intent.DIRECTORY_EMPLOYEE_DEPARTMENT,
                Intent.PROFILE_JOB_TITLE,
                Intent.PROFILE_DEPARTMENT,
                Intent.PROFILE_WORK_UNIT,
                Intent.PROFILE_MANAGER,
                Intent.PROFILE_EMPLOYMENT,
            }
        ),
        endpoint="employment",
        description=(
            "Lấy phòng ban, đơn vị công tác, cơ quan, chức danh và quản lý "
            "của một nhân viên đã được resolve."
        ),
        examples=(
            "Lò Văn Định ở cơ quan nào?",
            "Nhân viên mã 00234086 làm ở đâu?",
            "Người đó thuộc phòng nào?",
            "Đơn vị công tác của nhân viên vừa tìm.",
            "Chức danh và quản lý trực tiếp của nhân viên đó.",
            "lo van dinh o co quan nao",
        ),
        negative_examples=(
            "Danh sách nhân viên phòng Kế toán.",
            "Tìm nhân viên tên Lò Văn Định.",
            "Email của nhân viên đó.",
        ),
    ),
    _named_profile_tool(
        name="employee_get_contact",
        capability=Intent.PROFILE_CONTACT,
        intents=frozenset({Intent.PROFILE_CONTACT}),
        endpoint="contact",
        description="Lấy thông tin liên hệ của một nhân viên đã được resolve.",
        examples=(
            "Email công việc của nhân viên đó.",
            "Số điện thoại của Lò Văn Định.",
            "Thông tin liên hệ của người vừa tìm.",
            "Cho xem email của nhân viên mã 00234086.",
            "Liên hệ nhân viên này bằng số nào?",
        ),
        negative_examples=(
            "Email của tôi là gì?",
            "Người đó thuộc phòng nào?",
            "Danh sách nhân viên phòng Kế toán.",
        ),
        sensitive=True,
    ),
    _named_profile_tool(
        name="employee_get_education",
        capability=Intent.PROFILE_EDUCATION,
        intents=frozenset({Intent.PROFILE_EDUCATION}),
        endpoint="education",
        description="Lấy học vấn của một nhân viên đã được resolve.",
        examples=(
            "Trình độ học vấn của nhân viên đó.",
            "Lò Văn Định học chuyên ngành gì?",
            "Bằng cấp của người vừa tìm.",
            "Quá trình đào tạo của nhân viên mã 00234086.",
            "Nhân viên này học trường nào?",
        ),
        negative_examples=(
            "Trình độ học vấn của tôi.",
            "Nhân viên nào có chứng chỉ AWS?",
            "Chứng chỉ của nhân viên đó.",
        ),
    ),
    _named_profile_tool(
        name="employee_get_certificates",
        capability=Intent.PROFILE_CERTIFICATES,
        intents=frozenset({Intent.PROFILE_CERTIFICATES}),
        endpoint="certificates",
        description="Lấy chứng chỉ của một nhân viên đã được resolve.",
        examples=(
            "Nhân viên đó có những chứng chỉ nào?",
            "Chứng chỉ AWS của Lò Văn Định.",
            "Danh sách chứng nhận của người vừa tìm.",
            "Chứng chỉ của nhân viên mã 00234086.",
            "Xem chứng chỉ chuyên môn của cán bộ này.",
        ),
        negative_examples=(
            "Nhân viên nào có chứng chỉ AWS?",
            "Bằng cấp của nhân viên đó.",
            "Danh sách nhân viên phòng Kế toán.",
        ),
    ),
    _named_profile_tool(
        name="employee_get_work_history",
        capability=Intent.PROFILE_WORK_HISTORY,
        intents=frozenset(
            {
                Intent.PROFILE_WORK_HISTORY,
                Intent.PROFILE_HISTORY,
            }
        ),
        endpoint="work-history",
        description="Lấy lịch sử công tác của một nhân viên đã được resolve.",
        examples=(
            "Lịch sử công tác của nhân viên đó.",
            "Lò Văn Định từng làm ở đơn vị nào?",
            "Quá trình điều chuyển của người vừa tìm.",
            "Lịch sử bổ nhiệm của nhân viên này.",
            "Các vị trí trước đây của cán bộ đó.",
        ),
        negative_examples=(
            "Đơn vị hiện tại của nhân viên đó.",
            "Lịch sử chấm công.",
            "Danh sách nhân viên phòng Kế toán.",
        ),
    ),
    _named_profile_tool(
        name="employee_get_contracts",
        capability=Intent.PROFILE_CONTRACTS,
        intents=frozenset(
            {Intent.PROFILE_CONTRACTS, Intent.PROFILE_CONTRACT_EXPIRY}
        ),
        endpoint="contracts",
        description="Lấy hợp đồng của một nhân viên đã được resolve.",
        examples=(
            "Hợp đồng của nhân viên đó hết hạn khi nào?",
            "Cho xem hợp đồng của Lò Văn Định.",
            "Lịch sử hợp đồng của người vừa tìm.",
            "Hợp đồng hiện tại của nhân viên mã 00234086.",
            "Tình trạng hợp đồng của cán bộ này.",
        ),
        negative_examples=(
            "Hợp đồng của tôi hết hạn khi nào?",
            "Liệt kê hợp đồng hết hạn trong 30 ngày tới.",
            "Đơn vị công tác của nhân viên đó.",
        ),
    ),
    _named_profile_tool(
        name="employee_get_bank_tax",
        capability=Intent.PROFILE_BANK_TAX,
        intents=frozenset(
            {
                Intent.PROFILE_BANK_TAX,
                Intent.PROFILE_BANK_ACCOUNTS,
                Intent.PROFILE_TAX,
            }
        ),
        endpoint="bank-tax",
        description=(
            "Lấy thông tin ngân hàng và thuế của một nhân viên đã được "
            "resolve, qua policy nhạy cảm."
        ),
        examples=(
            "Thông tin ngân hàng của nhân viên đó.",
            "Mã số thuế của Lò Văn Định.",
            "Tài khoản nhận lương của người vừa tìm.",
            "Dữ liệu thuế của nhân viên mã 00234086.",
            "Ngân hàng của cán bộ này.",
        ),
        negative_examples=(
            "Tài khoản ngân hàng của tôi.",
            "Đơn vị công tác của nhân viên đó.",
            "Danh sách nhân viên phòng Kế toán.",
        ),
        sensitive=True,
    ),
    _named_profile_tool(
        name="employee_get_insurance",
        capability=Intent.PROFILE_INSURANCE,
        intents=frozenset({Intent.PROFILE_INSURANCE}),
        endpoint="insurance",
        description=(
            "Lấy thông tin bảo hiểm của một nhân viên đã được resolve, "
            "qua policy nhạy cảm."
        ),
        examples=(
            "Thông tin bảo hiểm của nhân viên đó.",
            "Mã bảo hiểm của Lò Văn Định.",
            "Bảo hiểm y tế của người vừa tìm.",
            "Hồ sơ bảo hiểm nhân viên mã 00234086.",
            "Nơi khám chữa bệnh của cán bộ này.",
        ),
        negative_examples=(
            "Thông tin bảo hiểm của tôi.",
            "Mã số thuế của nhân viên đó.",
            "Danh sách nhân viên phòng Kế toán.",
        ),
        sensitive=True,
    ),
    _named_profile_tool(
        name="employee_get_identity",
        capability=Intent.PROFILE_IDENTITY,
        intents=frozenset({Intent.PROFILE_IDENTITY}),
        endpoint="identity",
        description=(
            "Tra cứu nhóm định danh đã được mask của một nhân viên đã resolve: "
            "căn cước, ngày/nơi cấp, quốc tịch, dân tộc, tôn giáo và hôn nhân."
        ),
        examples=(
            "Dân tộc của Lò Văn Định.",
            "CCCD của nhân viên đó cấp ngày nào?",
            "Quốc tịch của nhân viên mã 00234086.",
            "Tình trạng hôn nhân của người vừa tìm.",
            "Nơi cấp căn cước của cán bộ này.",
            "dan toc cua lo van dinh",
        ),
        negative_examples=(
            "Dân tộc của tôi.",
            "Địa chỉ của Lò Văn Định.",
            "Nhân viên nào có chứng chỉ AWS?",
        ),
        sensitive=True,
    ),
    _named_profile_tool(
        name="employee_get_addresses",
        capability=Intent.PROFILE_ADDRESS,
        intents=frozenset({Intent.PROFILE_ADDRESS}),
        endpoint="addresses",
        description=(
            "Tra cứu hộ khẩu, thường trú, nơi ở hiện tại, quê quán và nơi sinh "
            "của một nhân viên đã resolve."
        ),
        examples=(
            "Nơi ở hiện tại của Lò Văn Định.",
            "Địa chỉ thường trú của nhân viên đó.",
            "Hộ khẩu của nhân viên mã 00234086.",
            "Quê quán của người vừa tìm.",
            "Cán bộ này đang sống ở đâu?",
            "dia chi cua lo van dinh",
        ),
        negative_examples=(
            "Nơi ở hiện tại của tôi.",
            "Đơn vị công tác của Lò Văn Định.",
            "Danh sách nhân viên phòng Kế toán.",
        ),
        sensitive=True,
    ),
    _named_profile_tool(
        name="employee_get_recruitment",
        capability=Intent.PROFILE_RECRUITMENT,
        intents=frozenset({Intent.PROFILE_RECRUITMENT}),
        endpoint="recruitment",
        description=(
            "Tra cứu ngày/hình thức tuyển dụng, ngày vào TCT hoặc đơn vị và "
            "cơ quan tuyển dụng của một nhân viên đã resolve."
        ),
        examples=(
            "Lò Văn Định vào TCT từ ngày nào?",
            "Ngày tuyển dụng của nhân viên đó.",
            "Hình thức tuyển dụng của nhân viên mã 00234086.",
            "Cơ quan nào đã tuyển người vừa tìm?",
            "Ngày cán bộ này vào đơn vị.",
            "lo van dinh vao tct tu ngay nao",
        ),
        negative_examples=(
            "Tôi vào TCT từ ngày nào?",
            "Hợp đồng của Lò Văn Định hết hạn khi nào?",
            "Lịch sử điều chuyển của nhân viên đó.",
        ),
    ),
    _named_profile_tool(
        name="employee_get_training_history",
        capability=Intent.PROFILE_TRAINING_HISTORY,
        intents=frozenset({Intent.PROFILE_TRAINING_HISTORY}),
        endpoint="training-history",
        description=(
            "Tra cứu lịch sử đào tạo bồi dưỡng, khóa học và cam kết đào tạo "
            "của một nhân viên đã resolve."
        ),
        examples=(
            "Lịch sử đào tạo của Lò Văn Định.",
            "Nhân viên đó từng học những khóa nào?",
            "Quá trình bồi dưỡng của nhân viên mã 00234086.",
            "Cam kết đào tạo của người vừa tìm.",
            "Các khóa học cán bộ này đã tham gia.",
            "lich su dao tao cua lo van dinh",
        ),
        negative_examples=(
            "Lịch sử đào tạo của tôi.",
            "Trình độ học vấn của Lò Văn Định.",
            "Chứng chỉ của nhân viên đó.",
        ),
    ),
    _named_profile_tool(
        name="employee_get_appointment_history",
        capability=Intent.PROFILE_APPOINTMENT_HISTORY,
        intents=frozenset({Intent.PROFILE_APPOINTMENT_HISTORY}),
        endpoint="appointment-history",
        description=(
            "Tra cứu lịch sử bổ nhiệm, quá trình giữ chức và quyết định bổ "
            "nhiệm của một nhân viên đã resolve."
        ),
        examples=(
            "Lịch sử bổ nhiệm của Lò Văn Định.",
            "Nhân viên đó từng giữ chức vụ nào?",
            "Quá trình giữ chức của nhân viên mã 00234086.",
            "Quyết định bổ nhiệm của người vừa tìm.",
            "Cán bộ này đã được bổ nhiệm những lần nào?",
            "lich su bo nhiem cua lo van dinh",
        ),
        negative_examples=(
            "Quá trình bổ nhiệm của tôi.",
            "Chức danh hiện tại của Lò Văn Định.",
            "Lịch sử điều chuyển của nhân viên đó.",
        ),
    ),
    _named_profile_tool(
        name="employee_get_transfer_history",
        capability=Intent.PROFILE_TRANSFER_HISTORY,
        intents=frozenset({Intent.PROFILE_TRANSFER_HISTORY}),
        endpoint="transfer-history",
        description=(
            "Tra cứu lịch sử điều chuyển, luân chuyển và chuyển đơn vị của một "
            "nhân viên đã resolve."
        ),
        examples=(
            "Lò Văn Định đã từng điều chuyển chưa?",
            "Lịch sử luân chuyển của nhân viên đó.",
            "Nhân viên mã 00234086 đã chuyển đơn vị những lần nào?",
            "Quá trình điều chuyển của người vừa tìm.",
            "Cán bộ này từng công tác tại các đơn vị nào?",
            "lo van dinh da tung dieu chuyen chua",
        ),
        negative_examples=(
            "Lịch sử điều chuyển của tôi.",
            "Đơn vị hiện tại của Lò Văn Định.",
            "Quá trình bổ nhiệm của nhân viên đó.",
        ),
    ),
    _named_profile_tool(
        name="employee_get_family_relations",
        capability=Intent.PROFILE_FAMILY_RELATIONS,
        intents=frozenset({Intent.PROFILE_FAMILY_RELATIONS}),
        endpoint="family-relations",
        description=(
            "Tra cứu quan hệ gia đình, người thân và thân nhân của một nhân "
            "viên đã resolve."
        ),
        examples=(
            "Người thân của Lò Văn Định.",
            "Quan hệ gia đình của nhân viên đó.",
            "Thông tin vợ chồng của nhân viên mã 00234086.",
            "Con cái của người vừa tìm.",
            "Danh sách thân nhân của cán bộ này.",
            "nguoi than cua lo van dinh",
        ),
        negative_examples=(
            "Người thân của tôi.",
            "Tình trạng hôn nhân của Lò Văn Định.",
            "Danh sách nhân viên phòng Kế toán.",
        ),
        sensitive=True,
    ),
    _named_profile_tool(
        name="employee_get_rewards",
        capability=Intent.PROFILE_REWARDS,
        intents=frozenset({Intent.PROFILE_REWARDS}),
        endpoint="rewards",
        description=(
            "Tra cứu khen thưởng, thành tích, bằng khen và quyết định khen "
            "thưởng của một nhân viên đã resolve."
        ),
        examples=(
            "Lò Văn Định đã được khen thưởng gì?",
            "Thành tích của nhân viên đó.",
            "Bằng khen của nhân viên mã 00234086.",
            "Lịch sử khen thưởng của người vừa tìm.",
            "Quyết định khen thưởng của cán bộ này.",
            "khen thuong cua lo van dinh",
        ),
        negative_examples=(
            "Tôi đã được khen thưởng gì?",
            "Kỷ luật của Lò Văn Định.",
            "Chứng chỉ của nhân viên đó.",
        ),
        sensitive=True,
    ),
    _named_profile_tool(
        name="employee_get_disciplines",
        capability=Intent.PROFILE_DISCIPLINES,
        intents=frozenset({Intent.PROFILE_DISCIPLINES}),
        endpoint="disciplines",
        description=(
            "Tra cứu lịch sử và quyết định kỷ luật của một nhân viên đã "
            "resolve."
        ),
        examples=(
            "Kỷ luật của Lò Văn Định.",
            "Nhân viên đó từng bị xử lý kỷ luật chưa?",
            "Quyết định kỷ luật của nhân viên mã 00234086.",
            "Lịch sử kỷ luật của người vừa tìm.",
            "Hình thức kỷ luật của cán bộ này.",
            "ky luat cua lo van dinh",
        ),
        negative_examples=(
            "Lịch sử kỷ luật của tôi.",
            "Khen thưởng của Lò Văn Định.",
            "Lịch sử điều chuyển của nhân viên đó.",
        ),
        sensitive=True,
    ),
    _named_profile_tool(
        name="employee_get_evaluations",
        capability=Intent.PROFILE_EVALUATIONS,
        intents=frozenset({Intent.PROFILE_EVALUATIONS}),
        endpoint="evaluations",
        description=(
            "Tra cứu kết quả đánh giá, xếp loại và nhận xét đơn vị của một "
            "nhân viên đã resolve."
        ),
        examples=(
            "Kết quả đánh giá của Lò Văn Định.",
            "Nhân viên đó được xếp loại thế nào?",
            "Lịch sử đánh giá của nhân viên mã 00234086.",
            "Nhận xét đơn vị về người vừa tìm.",
            "Đánh giá gần nhất của cán bộ này.",
            "danh gia cua lo van dinh",
        ),
        negative_examples=(
            "Kết quả đánh giá của tôi.",
            "Khen thưởng của Lò Văn Định.",
            "Quá trình bổ nhiệm của nhân viên đó.",
        ),
        sensitive=True,
    ),
    _named_profile_tool(
        name="employee_get_party_union",
        capability=Intent.PROFILE_PARTY_UNION,
        intents=frozenset({Intent.PROFILE_PARTY_UNION}),
        endpoint="party-union",
        description=(
            "Tra cứu thông tin Đảng, Đoàn và sinh hoạt Đoàn của một nhân viên "
            "đã resolve."
        ),
        examples=(
            "Lò Văn Định có phải Đảng viên không?",
            "Ngày vào Đảng của nhân viên đó.",
            "Nhân viên mã 00234086 vào Đoàn ngày nào?",
            "Lịch sử sinh hoạt Đoàn của người vừa tìm.",
            "Cán bộ này có phải Đoàn viên không?",
            "ngay vao doan cua lo van dinh",
        ),
        negative_examples=(
            "Tôi có phải Đảng viên không?",
            "Tôn giáo của Lò Văn Định.",
            "Sở thích của nhân viên đó.",
        ),
        sensitive=True,
    ),
    _named_profile_tool(
        name="employee_get_preferences",
        capability=Intent.PROFILE_PREFERENCES,
        intents=frozenset({Intent.PROFILE_PREFERENCES}),
        endpoint="preferences",
        description=(
            "Tra cứu mục tiêu cá nhân, sở thích, điểm mạnh và điểm yếu của một "
            "nhân viên đã resolve."
        ),
        examples=(
            "Sở thích của Lò Văn Định.",
            "Mục tiêu cá nhân của nhân viên đó.",
            "Điểm mạnh của nhân viên mã 00234086.",
            "Điểm yếu của người vừa tìm.",
            "Thông tin sở thích của cán bộ này.",
            "so thich cua lo van dinh",
        ),
        negative_examples=(
            "Sở thích của tôi.",
            "Sở trường công tác của Lò Văn Định.",
            "Kỹ năng của nhân viên đó.",
        ),
        sensitive=True,
    ),
)
