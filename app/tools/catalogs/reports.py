from app.routing.taxonomy import Intent, SubjectType
from app.tools.definitions import (
    ContractExpiringArguments,
    Domain,
    HttpMethod,
    Operation,
    RiskLevel,
    RouteType,
    SubjectScope,
    ToolDefinition,
)

REPORT_TOOLS = (
    ToolDefinition(
        name="contract_list_expiring",
        domain=Domain.REPORTING,
        capability=Intent.REPORT_CONTRACTS_EXPIRING.value,
        intent=Intent.REPORT_CONTRACTS_EXPIRING,
        intents=frozenset({Intent.REPORT_CONTRACTS_EXPIRING}),
        operation=Operation.LIST,
        route_type=RouteType.QUERY,
        risk_level=RiskLevel.READ,
        description=(
            "Liệt kê hợp đồng lao động sắp hết hạn trong một khoảng ngày hoặc "
            "số ngày tới; có thể giới hạn theo phòng ban, công ty và loại hợp đồng."
        ),
        endpoint="/api/v1/hrm/contracts/expiring",
        http_method=HttpMethod.POST,
        argument_schema=ContractExpiringArguments,
        examples=(
            "Liệt kê hợp đồng hết hạn trong 30 ngày tới.",
            "Những hợp đồng nào sắp hết hạn?",
            "Danh sách nhân viên sắp hết hợp đồng trong quý này.",
            "Báo cáo hợp đồng đến hạn từ ngày 1/8 đến 31/8.",
            "Hợp đồng lao động sắp hết hạn của phòng Kế toán.",
            "liet ke hop dong het han trong 30 ngay toi",
        ),
        negative_examples=(
            "Hợp đồng của tôi hết hạn khi nào?",
            "Hợp đồng của Lò Văn Định.",
            "Tạo đơn nghỉ phép.",
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
        required_actor_capability="report.contracts.expiring",
        version="1.0",
    ),
)

