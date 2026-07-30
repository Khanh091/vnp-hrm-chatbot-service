from __future__ import annotations

from enum import Enum


class QueryRoute(str, Enum):
    KNOWLEDGE = "knowledge"
    DATA_QUERY = "data_query"
    TASK = "task"
    GENERAL = "general"
    UNSUPPORTED = "unsupported"
    UNSAFE = "unsafe"


class Operation(str, Enum):
    READ = "read"
    CREATE = "create"
    UPDATE = "update"
    CANCEL = "cancel"
    NONE = "none"

    # Temporary source compatibility. These names serialize as "read".
    GET = "read"
    LIST = "read"
    CHECK = "read"
    EXPLAIN = "read"
    SEARCH = "read"
    NAVIGATE = "read"
    SUMMARIZE = "read"

    @classmethod
    def _missing_(cls, value: object) -> Operation | None:
        legacy_read_operations = {
            "get",
            "list",
            "check",
            "explain",
            "search",
            "navigate",
            "summarize",
        }
        if value in legacy_read_operations:
            return cls.READ
        return None


class SubjectScope(str, Enum):
    SELF = "self"
    NAMED_EMPLOYEE = "named_employee"
    DEPARTMENT = "department"
    COMPANY = "company"
    GENERAL = "general"
    UNKNOWN = "unknown"

    # Retained for persisted conversations created by the previous taxonomy.
    DIRECT_REPORTS = "direct_reports"


class SubjectType(str, Enum):
    SELF = "self"
    EMPLOYEE = "employee"
    DEPARTMENT = "department"
    COMPANY = "company"
    GENERAL = "general"


class Intent(str, Enum):
    PROFILE_BASIC = "profile.basic"
    PROFILE_SUMMARY = "profile.summary"
    PROFILE_EMPLOYEE_CODE = "profile.employee_code"
    PROFILE_JOB_TITLE = "profile.job_title"
    PROFILE_DEPARTMENT = "profile.department"
    PROFILE_WORK_UNIT = "profile.work_unit"
    PROFILE_MANAGER = "profile.manager"
    PROFILE_CONTACT = "profile.contact"
    PROFILE_IDENTITY = "profile.identity"
    PROFILE_ADDRESS = "profile.address"
    PROFILE_RECRUITMENT = "profile.recruitment"
    PROFILE_BANK_TAX = "profile.bank_tax"
    PROFILE_EMPLOYMENT = "profile.employment"
    PROFILE_WORK_HISTORY = "profile.work_history"
    PROFILE_APPOINTMENT_HISTORY = "profile.appointment_history"
    PROFILE_TRANSFER_HISTORY = "profile.transfer_history"
    PROFILE_EDUCATION = "profile.education"
    PROFILE_CERTIFICATES = "profile.certificates"
    PROFILE_TRAINING_HISTORY = "profile.training_history"
    PROFILE_SKILLS = "profile.skills"
    PROFILE_HISTORY = "profile.history"
    PROFILE_CONTRACTS = "profile.contracts"
    PROFILE_CONTRACT_EXPIRY = "profile.contract_expiry"
    PROFILE_INSURANCE = "profile.insurance"
    PROFILE_FAMILY_RELATIONS = "profile.family_relations"
    PROFILE_REWARDS = "profile.rewards"
    PROFILE_DISCIPLINES = "profile.disciplines"
    PROFILE_EVALUATIONS = "profile.evaluations"
    PROFILE_PARTY_UNION = "profile.party_union"
    PROFILE_PERSONAL_BACKGROUND = "profile.personal_background"
    PROFILE_PREFERENCES = "profile.preferences"
    PROFILE_FAMILY_ECONOMY = "profile.family_economy"
    PROFILE_HEALTH = "profile.health"
    PROFILE_TAX = "profile.tax"
    PROFILE_BANK_ACCOUNTS = "profile.bank_accounts"

    LEAVE_BALANCE = "leave.balance"
    LEAVE_USED = "leave.used"
    LEAVE_HISTORY = "leave.history"
    LEAVE_REQUEST_STATUS = "leave.request_status"
    LEAVE_CALENDAR = "leave.calendar"
    LEAVE_ELIGIBILITY = "leave.eligibility"
    LEAVE_TYPES = "leave.types"
    LEAVE_CREATE = "leave.create"
    LEAVE_UPDATE = "leave.update"
    LEAVE_CANCEL = "leave.cancel"

    ATTENDANCE_DAILY = "attendance.daily"
    ATTENDANCE_MONTHLY = "attendance.monthly"
    ATTENDANCE_CHECK_IN = "attendance.check_in"
    ATTENDANCE_CHECK_OUT = "attendance.check_out"
    ATTENDANCE_WORKED_HOURS = "attendance.worked_hours"
    ATTENDANCE_OVERTIME_HOURS = "attendance.overtime_hours"
    ATTENDANCE_LATE_COUNT = "attendance.late_count"
    ATTENDANCE_MISSING_PUNCH_COUNT = "attendance.missing_punch_count"
    ATTENDANCE_MISSING_WORK_EXPLANATION = (
        "attendance.missing_work_explanation"
    )
    ATTENDANCE_ACTUAL_WORK_DAYS = "attendance.actual_work_days"
    ATTENDANCE_HISTORY = "attendance.history"
    ATTENDANCE_MONTHLY_SUMMARY = "attendance.monthly_summary"
    ATTENDANCE_LATE_SUMMARY = "attendance.late_summary"
    ATTENDANCE_MISSING_PUNCH = "attendance.missing_punch"
    ATTENDANCE_MISSING_WORK_CONTEXT = "attendance.missing_work_context"

    DIRECTORY_EMPLOYEE_SEARCH = "directory.employee_search"
    DIRECTORY_EMPLOYEE_PROFILE = "directory.employee_profile"
    DIRECTORY_EMPLOYEE_DEPARTMENT = "directory.employee_department"
    DIRECTORY_DEPARTMENT_EMPLOYEES = "directory.department_employees"
    DIRECTORY_EMPLOYEE_BY_CERTIFICATE = "directory.employee_by_certificate"

    REPORT_CONTRACTS_EXPIRING = "report.contracts_expiring"
    REPORT_TERMINATED_EMPLOYEES = "report.terminated_employees"
    REPORT_DEPARTMENT_HR_SUMMARY = "report.department_hr_summary"

    KNOWLEDGE_LEAVE_POLICY = "knowledge.leave_policy"
    KNOWLEDGE_ATTENDANCE_POLICY = "knowledge.attendance_policy"
    KNOWLEDGE_CONTRACT_POLICY = "knowledge.contract_policy"
    KNOWLEDGE_PROFILE_PROCEDURE = "knowledge.profile_procedure"
    KNOWLEDGE_GENERAL_HR_POLICY = "knowledge.general_hr_policy"

    GENERAL_GREETING = "general.greeting"
    GENERAL_CAPABILITIES = "general.capabilities"
    GENERAL_HELP = "general.help"

    UNSUPPORTED_OUT_OF_SCOPE = "unsupported.out_of_scope"
    UNSAFE_PROMPT_INJECTION = "unsafe.prompt_injection"
    UNSAFE_FORBIDDEN_ADMIN_ACTION = "unsafe.forbidden_admin_action"


READ_TOOL_INTENTS = frozenset(
    intent
    for intent in Intent
    if intent.value.startswith(("profile.", "leave.", "attendance."))
    and intent
    not in {Intent.LEAVE_CREATE, Intent.LEAVE_UPDATE, Intent.LEAVE_CANCEL}
)
