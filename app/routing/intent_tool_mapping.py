from __future__ import annotations

from app.routing.taxonomy import Intent

INTENT_TO_TOOL_NAMES: dict[Intent, tuple[str, ...]] = {
    Intent.PROFILE_SUMMARY: ("profile_get_summary",),
    Intent.PROFILE_EMPLOYEE_CODE: ("profile_get_summary",),
    Intent.PROFILE_JOB_TITLE: ("profile_get_employment",),
    Intent.PROFILE_DEPARTMENT: ("profile_get_employment",),
    Intent.PROFILE_WORK_UNIT: ("profile_get_employment",),
    Intent.PROFILE_MANAGER: ("profile_get_employment",),
    Intent.PROFILE_EMPLOYMENT: ("profile_get_employment",),
    Intent.PROFILE_CONTACT: ("profile_get_contact",),
    Intent.PROFILE_WORK_HISTORY: ("profile_get_history",),
    Intent.PROFILE_APPOINTMENT_HISTORY: ("profile_get_history",),
    Intent.PROFILE_TRANSFER_HISTORY: ("profile_get_history",),
    Intent.PROFILE_HISTORY: ("profile_get_history",),
    Intent.PROFILE_EDUCATION: ("profile_get_education",),
    Intent.PROFILE_CERTIFICATES: ("profile_get_certificates",),
    Intent.PROFILE_SKILLS: ("profile_get_skills",),
    Intent.PROFILE_INSURANCE: ("profile_get_insurance",),
    Intent.PROFILE_TAX: ("profile_get_tax",),
    Intent.PROFILE_BANK_ACCOUNTS: ("profile_get_bank_accounts",),
    Intent.PROFILE_CONTRACTS: ("profile_get_contracts",),
    Intent.PROFILE_CONTRACT_EXPIRY: ("profile_get_contracts",),
    Intent.ATTENDANCE_DAILY: ("attendance_get_daily",),
    Intent.ATTENDANCE_CHECK_IN: ("attendance_get_daily",),
    Intent.ATTENDANCE_CHECK_OUT: ("attendance_get_daily",),
    Intent.ATTENDANCE_WORKED_HOURS: ("attendance_get_daily",),
    Intent.ATTENDANCE_MONTHLY: ("attendance_get_monthly_summary",),
    Intent.ATTENDANCE_MONTHLY_SUMMARY: ("attendance_get_monthly_summary",),
    Intent.ATTENDANCE_OVERTIME_HOURS: ("attendance_get_monthly_summary",),
    Intent.ATTENDANCE_LATE_COUNT: ("attendance_get_monthly_summary",),
    Intent.ATTENDANCE_MISSING_PUNCH_COUNT: (
        "attendance_get_monthly_summary",
    ),
    Intent.ATTENDANCE_ACTUAL_WORK_DAYS: ("attendance_get_monthly_summary",),
    Intent.ATTENDANCE_HISTORY: ("attendance_get_history",),
    Intent.ATTENDANCE_LATE_SUMMARY: ("attendance_get_late_summary",),
    Intent.ATTENDANCE_MISSING_PUNCH: (
        "attendance_get_missing_punch_summary",
    ),
    Intent.ATTENDANCE_MISSING_WORK_EXPLANATION: (
        "attendance_get_missing_work_context",
    ),
    Intent.ATTENDANCE_MISSING_WORK_CONTEXT: (
        "attendance_get_missing_work_context",
    ),
    Intent.LEAVE_BALANCE: ("leave_get_balance",),
    Intent.LEAVE_USED: ("leave_get_used",),
    Intent.LEAVE_HISTORY: ("leave_get_history",),
    Intent.LEAVE_REQUEST_STATUS: ("leave_get_request_status",),
    Intent.LEAVE_CALENDAR: ("leave_get_calendar",),
    Intent.LEAVE_ELIGIBILITY: ("leave_check_eligibility",),
    Intent.LEAVE_TYPES: ("leave_list_types",),
    Intent.LEAVE_CREATE: ("leave_create_request",),
    Intent.LEAVE_UPDATE: ("leave_update_request",),
    Intent.LEAVE_CANCEL: ("leave_cancel_request",),
}


def tool_names_for_intent(intent: Intent | None) -> tuple[str, ...]:
    if intent is None:
        return ()
    return INTENT_TO_TOOL_NAMES.get(intent, ())


def tool_supports_intent(tool_name: str, intent: Intent) -> bool:
    return tool_name in tool_names_for_intent(intent)
