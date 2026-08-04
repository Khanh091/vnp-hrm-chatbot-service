from __future__ import annotations

from collections.abc import Iterable

from pydantic import BaseModel, ConfigDict

from app.routing.taxonomy import Intent, Operation, SubjectType
from app.tools.definitions import Domain, RiskLevel, ToolDefinition
from app.tools.registry import ToolRegistry


class CapabilityDefinition(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    domain: Domain
    operation: Operation
    supported_intents: frozenset[Intent]
    supported_subject_types: frozenset[SubjectType]
    risk_level: RiskLevel
    description: str


class RoutingResolutionError(RuntimeError):
    reason_code: str

    def __init__(self, reason_code: str) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code


class IntentNotRecognizedError(RoutingResolutionError):
    def __init__(self) -> None:
        super().__init__("INTENT_NOT_RECOGNIZED")


class NoCapabilityForIntentError(RoutingResolutionError):
    def __init__(self) -> None:
        super().__init__("NO_CAPABILITY_FOR_INTENT")


class NoToolForCapabilityError(RoutingResolutionError):
    def __init__(self) -> None:
        super().__init__("NO_TOOL_FOR_CAPABILITY")


class NoSubjectCompatibleToolError(RoutingResolutionError):
    def __init__(self) -> None:
        super().__init__("NO_SUBJECT_COMPATIBLE_TOOL")


class NoRetrievalCandidatesError(RoutingResolutionError):
    def __init__(self) -> None:
        super().__init__("NO_RETRIEVAL_CANDIDATES")


def _capability(
    name: str,
    domain: Domain,
    intents: Iterable[Intent],
    subjects: Iterable[SubjectType],
    description: str,
    *,
    operation: Operation = Operation.READ,
    risk_level: RiskLevel = RiskLevel.READ,
) -> CapabilityDefinition:
    return CapabilityDefinition(
        name=name,
        domain=domain,
        operation=operation,
        supported_intents=frozenset(intents),
        supported_subject_types=frozenset(subjects),
        risk_level=risk_level,
        description=description,
    )


_SELF_EMPLOYEE = (SubjectType.SELF, SubjectType.EMPLOYEE)
_SELF = (SubjectType.SELF,)

_CAPABILITIES: tuple[CapabilityDefinition, ...] = (
    _capability(
        "employee_basic_read",
        Domain.PROFILE,
        (
            Intent.PROFILE_BASIC,
            Intent.PROFILE_SUMMARY,
            Intent.PROFILE_EMPLOYEE_CODE,
            Intent.DIRECTORY_EMPLOYEE_PROFILE,
        ),
        _SELF_EMPLOYEE,
        "Đọc thông tin hồ sơ cơ bản của một nhân viên.",
    ),
    _capability(
        "employee_employment_read",
        Domain.PROFILE,
        (
            Intent.PROFILE_EMPLOYMENT,
            Intent.PROFILE_JOB_TITLE,
            Intent.PROFILE_DEPARTMENT,
            Intent.PROFILE_WORK_UNIT,
            Intent.PROFILE_MANAGER,
            Intent.DIRECTORY_EMPLOYEE_DEPARTMENT,
        ),
        _SELF_EMPLOYEE,
        "Đọc đơn vị, phòng ban, chức danh và quản lý của nhân viên.",
    ),
    _capability(
        "employee_contact_read",
        Domain.PROFILE,
        (Intent.PROFILE_CONTACT,),
        _SELF_EMPLOYEE,
        "Đọc thông tin liên hệ của nhân viên.",
        risk_level=RiskLevel.SENSITIVE_READ,
    ),
    _capability(
        "employee_identity_read",
        Domain.PROFILE,
        (Intent.PROFILE_IDENTITY,),
        _SELF_EMPLOYEE,
        "Đọc thông tin định danh của nhân viên.",
        risk_level=RiskLevel.SENSITIVE_READ,
    ),
    _capability(
        "employee_address_read",
        Domain.PROFILE,
        (Intent.PROFILE_ADDRESS,),
        _SELF_EMPLOYEE,
        "Đọc thông tin địa chỉ của nhân viên.",
        risk_level=RiskLevel.SENSITIVE_READ,
    ),
    _capability(
        "employee_recruitment_read",
        Domain.PROFILE,
        (Intent.PROFILE_RECRUITMENT,),
        _SELF_EMPLOYEE,
        "Đọc thông tin tuyển dụng của nhân viên.",
    ),
    _capability(
        "employee_bank_tax_read",
        Domain.PROFILE,
        (
            Intent.PROFILE_BANK_TAX,
            Intent.PROFILE_BANK_ACCOUNTS,
            Intent.PROFILE_TAX,
        ),
        _SELF_EMPLOYEE,
        "Đọc thông tin ngân hàng và thuế của nhân viên.",
        risk_level=RiskLevel.SENSITIVE_READ,
    ),
    _capability(
        "employee_work_history_read",
        Domain.PROFILE,
        (Intent.PROFILE_HISTORY, Intent.PROFILE_WORK_HISTORY),
        _SELF_EMPLOYEE,
        "Đọc lịch sử công tác của nhân viên.",
    ),
    _capability(
        "employee_appointment_history_read",
        Domain.PROFILE,
        (Intent.PROFILE_APPOINTMENT_HISTORY,),
        _SELF_EMPLOYEE,
        "Đọc lịch sử bổ nhiệm của nhân viên.",
    ),
    _capability(
        "employee_transfer_history_read",
        Domain.PROFILE,
        (Intent.PROFILE_TRANSFER_HISTORY,),
        _SELF_EMPLOYEE,
        "Đọc lịch sử điều chuyển của nhân viên.",
    ),
    _capability(
        "employee_education_read",
        Domain.PROFILE,
        (Intent.PROFILE_EDUCATION,),
        _SELF_EMPLOYEE,
        "Đọc thông tin học vấn của nhân viên.",
    ),
    _capability(
        "employee_certificate_read",
        Domain.PROFILE,
        (Intent.PROFILE_CERTIFICATES,),
        _SELF_EMPLOYEE,
        "Đọc chứng chỉ của nhân viên.",
    ),
    _capability(
        "employee_training_history_read",
        Domain.PROFILE,
        (Intent.PROFILE_TRAINING_HISTORY,),
        _SELF_EMPLOYEE,
        "Đọc lịch sử đào tạo của nhân viên.",
    ),
    _capability(
        "employee_skill_read",
        Domain.PROFILE,
        (Intent.PROFILE_SKILLS,),
        _SELF_EMPLOYEE,
        "Đọc kỹ năng của nhân viên.",
    ),
    _capability(
        "employee_contract_read",
        Domain.PROFILE,
        (Intent.PROFILE_CONTRACTS, Intent.PROFILE_CONTRACT_EXPIRY),
        _SELF_EMPLOYEE,
        "Đọc thông tin hợp đồng của một nhân viên.",
        risk_level=RiskLevel.SENSITIVE_READ,
    ),
    _capability(
        "employee_insurance_read",
        Domain.PROFILE,
        (Intent.PROFILE_INSURANCE,),
        _SELF_EMPLOYEE,
        "Đọc thông tin bảo hiểm của nhân viên.",
        risk_level=RiskLevel.SENSITIVE_READ,
    ),
    _capability(
        "employee_family_relations_read",
        Domain.PROFILE,
        (Intent.PROFILE_FAMILY_RELATIONS,),
        _SELF_EMPLOYEE,
        "Đọc quan hệ gia đình của nhân viên.",
        risk_level=RiskLevel.FAMILY_RELATIONS_READ,
    ),
    _capability(
        "employee_reward_read",
        Domain.PROFILE,
        (Intent.PROFILE_REWARDS,),
        _SELF_EMPLOYEE,
        "Đọc lịch sử khen thưởng của nhân viên.",
        risk_level=RiskLevel.SENSITIVE_READ,
    ),
    _capability(
        "employee_discipline_read",
        Domain.PROFILE,
        (Intent.PROFILE_DISCIPLINES,),
        _SELF_EMPLOYEE,
        "Đọc lịch sử kỷ luật của nhân viên.",
        risk_level=RiskLevel.SENSITIVE_READ,
    ),
    _capability(
        "employee_evaluation_read",
        Domain.PROFILE,
        (Intent.PROFILE_EVALUATIONS,),
        _SELF_EMPLOYEE,
        "Đọc kết quả đánh giá của nhân viên.",
        risk_level=RiskLevel.SENSITIVE_READ,
    ),
    _capability(
        "employee_party_union_read",
        Domain.PROFILE,
        (Intent.PROFILE_PARTY_UNION,),
        _SELF_EMPLOYEE,
        "Đọc thông tin Đảng và đoàn thể của nhân viên.",
        risk_level=RiskLevel.SENSITIVE_READ,
    ),
    _capability(
        "employee_preference_read",
        Domain.PROFILE,
        (Intent.PROFILE_PREFERENCES,),
        _SELF_EMPLOYEE,
        "Đọc sở thích và mục tiêu cá nhân của nhân viên.",
        risk_level=RiskLevel.SENSITIVE_READ,
    ),
    _capability(
        "employee_personal_background_read",
        Domain.PROFILE,
        (Intent.PROFILE_PERSONAL_BACKGROUND,),
        _SELF_EMPLOYEE,
        "Đọc thông tin hoàn cảnh cá nhân của nhân viên.",
        risk_level=RiskLevel.PERSONAL_BACKGROUND_READ,
    ),
    _capability(
        "employee_family_economy_read",
        Domain.PROFILE,
        (Intent.PROFILE_FAMILY_ECONOMY,),
        _SELF_EMPLOYEE,
        "Đọc thông tin kinh tế gia đình của nhân viên.",
        risk_level=RiskLevel.FAMILY_ECONOMY_READ,
    ),
    _capability(
        "employee_health_read",
        Domain.PROFILE,
        (Intent.PROFILE_HEALTH,),
        _SELF_EMPLOYEE,
        "Đọc thông tin sức khỏe của nhân viên.",
        risk_level=RiskLevel.HEALTH_READ,
    ),
    _capability(
        "employee_attendance_daily_read",
        Domain.ATTENDANCE,
        (
            Intent.ATTENDANCE_DAILY,
            Intent.ATTENDANCE_CHECK_IN,
            Intent.ATTENDANCE_CHECK_OUT,
            Intent.ATTENDANCE_WORKED_HOURS,
        ),
        _SELF,
        "Đọc dữ liệu chấm công theo ngày.",
    ),
    _capability(
        "employee_attendance_monthly_read",
        Domain.ATTENDANCE,
        (
            Intent.ATTENDANCE_MONTHLY,
            Intent.ATTENDANCE_MONTHLY_SUMMARY,
            Intent.ATTENDANCE_OVERTIME_HOURS,
            Intent.ATTENDANCE_LATE_COUNT,
            Intent.ATTENDANCE_MISSING_PUNCH_COUNT,
            Intent.ATTENDANCE_ACTUAL_WORK_DAYS,
            Intent.ATTENDANCE_RECORDED_DAYS,
            Intent.ATTENDANCE_NO_ATTENDANCE_DAYS,
            Intent.ATTENDANCE_UNASSIGNED_SHIFT_WORKED_DAYS,
        ),
        _SELF,
        "Đọc tổng hợp chấm công theo tháng.",
    ),
    _capability(
        "employee_attendance_history_read",
        Domain.ATTENDANCE,
        (Intent.ATTENDANCE_HISTORY,),
        _SELF,
        "Đọc lịch sử chấm công.",
    ),
    _capability(
        "employee_attendance_late_read",
        Domain.ATTENDANCE,
        (Intent.ATTENDANCE_LATE_SUMMARY,),
        _SELF,
        "Đọc tổng hợp đi muộn.",
    ),
    _capability(
        "employee_attendance_missing_punch_read",
        Domain.ATTENDANCE,
        (Intent.ATTENDANCE_MISSING_PUNCH,),
        _SELF,
        "Đọc tổng hợp thiếu lượt chấm công.",
    ),
    _capability(
        "employee_attendance_missing_work_read",
        Domain.ATTENDANCE,
        (
            Intent.ATTENDANCE_MISSING_WORK_CONTEXT,
            Intent.ATTENDANCE_MISSING_WORK_EXPLANATION,
        ),
        _SELF,
        "Đọc ngữ cảnh giải thích thiếu công.",
    ),
    _capability(
        "employee_leave_balance_read",
        Domain.LEAVE,
        (Intent.LEAVE_BALANCE,),
        _SELF,
        "Đọc số dư phép.",
    ),
    _capability(
        "employee_leave_used_read",
        Domain.LEAVE,
        (Intent.LEAVE_USED,),
        _SELF,
        "Đọc số ngày phép đã dùng.",
    ),
    _capability(
        "employee_leave_request_read",
        Domain.LEAVE,
        (Intent.LEAVE_HISTORY, Intent.LEAVE_REQUEST_STATUS),
        _SELF,
        "Đọc lịch sử và trạng thái đơn nghỉ.",
    ),
    _capability(
        "employee_leave_calendar_read",
        Domain.LEAVE,
        (Intent.LEAVE_CALENDAR,),
        _SELF,
        "Đọc lịch nghỉ.",
    ),
    _capability(
        "employee_leave_eligibility_read",
        Domain.LEAVE,
        (Intent.LEAVE_ELIGIBILITY,),
        _SELF,
        "Kiểm tra điều kiện nghỉ.",
    ),
    _capability(
        "leave_type_list",
        Domain.LEAVE,
        (Intent.LEAVE_TYPES,),
        _SELF,
        "Liệt kê loại nghỉ.",
    ),
    _capability(
        "employee_leave_create",
        Domain.LEAVE,
        (Intent.LEAVE_CREATE,),
        _SELF,
        "Tạo đơn nghỉ.",
        operation=Operation.CREATE,
        risk_level=RiskLevel.WRITE,
    ),
    _capability(
        "employee_leave_update",
        Domain.LEAVE,
        (Intent.LEAVE_UPDATE,),
        _SELF,
        "Cập nhật đơn nghỉ.",
        operation=Operation.UPDATE,
        risk_level=RiskLevel.WRITE,
    ),
    _capability(
        "employee_leave_cancel",
        Domain.LEAVE,
        (Intent.LEAVE_CANCEL,),
        _SELF,
        "Hủy đơn nghỉ.",
        operation=Operation.CANCEL,
        risk_level=RiskLevel.WRITE,
    ),
    _capability(
        "employee_certificate_create",
        Domain.PROFILE,
        (Intent.PROFILE_CERTIFICATES,),
        _SELF,
        "Tạo bản ghi chứng chỉ hồ sơ tự khai.",
        operation=Operation.CREATE,
        risk_level=RiskLevel.WRITE,
    ),
    _capability(
        "employee_certificate_update",
        Domain.PROFILE,
        (Intent.PROFILE_CERTIFICATES,),
        _SELF,
        "Cập nhật bản ghi chứng chỉ hồ sơ tự khai.",
        operation=Operation.UPDATE,
        risk_level=RiskLevel.WRITE,
    ),
    _capability(
        "employee_certificate_delete",
        Domain.PROFILE,
        (Intent.PROFILE_CERTIFICATES,),
        _SELF,
        "Xóa bản ghi chứng chỉ hồ sơ tự khai.",
        operation=Operation.DELETE,
        risk_level=RiskLevel.WRITE,
    ),
    _capability(
        "employee_directory_search",
        Domain.DIRECTORY,
        (Intent.DIRECTORY_EMPLOYEE_SEARCH,),
        (SubjectType.EMPLOYEE,),
        "Tìm kiếm nhân viên theo tên hoặc mã.",
    ),
    _capability(
        "department_list",
        Domain.DIRECTORY,
        (Intent.DIRECTORY_DEPARTMENTS,),
        (SubjectType.COMPANY,),
        "List departments visible to the authenticated actor.",
    ),
    _capability(
        "department_employee_list",
        Domain.DIRECTORY,
        (Intent.DIRECTORY_DEPARTMENT_EMPLOYEES,),
        (SubjectType.DEPARTMENT,),
        "Liệt kê nhân viên trong một phòng ban.",
    ),
    _capability(
        "employee_department_membership_check",
        Domain.DIRECTORY,
        (Intent.DIRECTORY_EMPLOYEE_IN_DEPARTMENT,),
        (SubjectType.EMPLOYEE,),
        "Check membership against the actor's trusted department.",
    ),
    _capability(
        "employee_certificate_search",
        Domain.DIRECTORY,
        (Intent.DIRECTORY_EMPLOYEE_BY_CERTIFICATE,),
        (SubjectType.DEPARTMENT, SubjectType.COMPANY),
        "Tìm nhân viên theo chứng chỉ.",
    ),
    _capability(
        "contract_expiry_report",
        Domain.REPORTING,
        (Intent.REPORT_CONTRACTS_EXPIRING,),
        (SubjectType.DEPARTMENT, SubjectType.COMPANY),
        "Liệt kê hợp đồng sắp hết hạn.",
    ),
    _capability(
        "terminated_employee_report",
        Domain.REPORTING,
        (Intent.REPORT_TERMINATED_EMPLOYEES,),
        (SubjectType.DEPARTMENT, SubjectType.COMPANY),
        "Báo cáo nhân viên đã nghỉ việc.",
    ),
    _capability(
        "department_hr_summary_report",
        Domain.REPORTING,
        (Intent.REPORT_DEPARTMENT_HR_SUMMARY,),
        (SubjectType.DEPARTMENT, SubjectType.COMPANY),
        "Tổng hợp nhân sự theo phòng ban.",
    ),
)

# Profile write capabilities describe routable business work, even while no
# execution tool exists. Registry metadata remains the authority for whether a
# concrete resource/field is writable.
_PROFILE_WRITE_CAPABILITIES = tuple(
    _capability(
        f"employee_{intent.value.split('.', 1)[1]}_{operation.value}",
        Domain.PROFILE,
        (intent,),
        _SELF,
        f"Resolve profile {operation.value} for the authenticated employee.",
        operation=operation,
        risk_level=RiskLevel.WRITE,
    )
    for intent in Intent
    if intent.value.startswith("profile.") and intent is not Intent.PROFILE_CERTIFICATES
    for operation in (Operation.CREATE, Operation.UPDATE, Operation.DELETE)
)
_CAPABILITIES = (*_CAPABILITIES, *_PROFILE_WRITE_CAPABILITIES)

CAPABILITY_REGISTRY: dict[str, CapabilityDefinition] = {
    capability.name: capability for capability in _CAPABILITIES
}

_INTENT_CAPABILITIES: dict[Intent, frozenset[str]] = {
    intent: frozenset(
        capability.name
        for capability in _CAPABILITIES
        if intent in capability.supported_intents
    )
    for intent in Intent
}


def capability_names_for_intent(
    intent: Intent,
    operation: Operation | None = None,
) -> frozenset[str]:
    names = _INTENT_CAPABILITIES[intent]
    if operation is None:
        return names
    return frozenset(
        name for name in names if CAPABILITY_REGISTRY[name].operation is operation
    )


def common_capability_names(
    intents: Iterable[Intent],
) -> frozenset[str]:
    intent_list = tuple(intents)
    if not intent_list:
        return frozenset()
    common = set(capability_names_for_intent(intent_list[0]))
    for intent in intent_list[1:]:
        common.intersection_update(capability_names_for_intent(intent))
    return frozenset(common)


class CapabilityResolver:
    def __init__(
        self,
        registry: dict[str, CapabilityDefinition] | None = None,
    ) -> None:
        self._registry = registry if registry is not None else CAPABILITY_REGISTRY

    def resolve(
        self,
        *,
        intent: Intent | None,
        subject_type: SubjectType,
        operation: Operation = Operation.READ,
    ) -> list[CapabilityDefinition]:
        if intent is None:
            raise IntentNotRecognizedError()
        names = capability_names_for_intent(intent, operation)
        if not names:
            raise NoCapabilityForIntentError()
        capabilities = [
            self._registry[name]
            for name in sorted(names)
            if subject_type in self._registry[name].supported_subject_types
        ]
        if not capabilities:
            raise NoSubjectCompatibleToolError()
        return capabilities


class ToolResolver:
    def __init__(self, registry: ToolRegistry) -> None:
        self._registry = registry

    def resolve(
        self,
        *,
        capability: CapabilityDefinition,
        subject_type: SubjectType,
    ) -> list[ToolDefinition]:
        capability_tools = [
            tool
            for tool in self._registry.list_all()
            if tool.enabled and tool.capability_name == capability.name
        ]
        if not capability_tools:
            raise NoToolForCapabilityError()
        tools = [
            tool
            for tool in capability_tools
            if subject_type in tool.supported_subject_types
        ]
        if not tools:
            raise NoSubjectCompatibleToolError()
        return tools


__all__ = [
    "CAPABILITY_REGISTRY",
    "CapabilityDefinition",
    "CapabilityResolver",
    "IntentNotRecognizedError",
    "NoCapabilityForIntentError",
    "NoRetrievalCandidatesError",
    "NoSubjectCompatibleToolError",
    "NoToolForCapabilityError",
    "RoutingResolutionError",
    "ToolResolver",
    "capability_names_for_intent",
    "common_capability_names",
]
