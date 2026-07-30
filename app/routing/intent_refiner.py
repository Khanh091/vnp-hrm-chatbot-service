from __future__ import annotations

import re

from app.context.entity_resolver import EntityResolver
from app.routing.schemas import Domain, QueryClassification
from app.routing.taxonomy import (
    Intent,
    Operation,
    QueryRoute,
    SubjectScope,
    SubjectType,
)

_READ_REFINEMENTS: tuple[
    tuple[re.Pattern[str], Domain, Intent, SubjectScope | None],
    ...,
] = (
    (
        re.compile(
            r"\b(?:CCCD|CMND|căn cước|số căn cước|ngày cấp|nơi cấp|"
            r"quốc tịch|dân tộc|tôn giáo|giới tính|"
            r"tình trạng hôn nhân|tên gọi khác)\b",
            re.I,
        ),
        Domain.PROFILE,
        Intent.PROFILE_IDENTITY,
        None,
    ),
    (
        re.compile(
            r"\b(?:hộ khẩu|thường trú|nơi ở hiện tại|địa chỉ|quê quán|"
            r"nơi sinh|sống ở đâu)\b",
            re.I,
        ),
        Domain.PROFILE,
        Intent.PROFILE_ADDRESS,
        None,
    ),
    (
        re.compile(
            r"\b(?:ngày tuyển dụng|hình thức tuyển dụng|ngày vào công ty|"
            r"vào TCT|ngày vào đơn vị|cơ quan tuyển dụng|"
            r"sở trường công tác)\b",
            re.I,
        ),
        Domain.PROFILE,
        Intent.PROFILE_RECRUITMENT,
        None,
    ),
    (
        re.compile(
            r"\b(?:đào tạo bồi dưỡng|khóa học|cam kết đào tạo|"
            r"lịch sử đào tạo)\b",
            re.I,
        ),
        Domain.PROFILE,
        Intent.PROFILE_TRAINING_HISTORY,
        None,
    ),
    (
        re.compile(
            r"\b(?:bổ nhiệm|lịch sử bổ nhiệm|quá trình giữ chức|"
            r"quyết định bổ nhiệm)\b",
            re.I,
        ),
        Domain.PROFILE,
        Intent.PROFILE_APPOINTMENT_HISTORY,
        None,
    ),
    (
        re.compile(
            r"\b(?:điều chuyển|luân chuyển|chuyển đơn vị|"
            r"lịch sử điều chuyển)\b",
            re.I,
        ),
        Domain.PROFILE,
        Intent.PROFILE_TRANSFER_HISTORY,
        None,
    ),
    (
        re.compile(
            r"\b(?:danh sách|liệt kê|những)\s+"
            r"(?:nhân viên|cán bộ|người).*(?:phòng|ban|đơn vị)\b",
            re.I,
        ),
        Domain.DIRECTORY,
        Intent.DIRECTORY_DEPARTMENT_EMPLOYEES,
        SubjectScope.DEPARTMENT,
    ),
    (
        re.compile(
            r"\b(?:nhân viên|cán bộ)\s+(?:mã\s+)?[A-Z0-9._-]+"
            r".*(?:thuộc phòng|ở cơ quan|làm ở đâu|thuộc đơn vị)\b",
            re.I,
        ),
        Domain.DIRECTORY,
        Intent.DIRECTORY_EMPLOYEE_DEPARTMENT,
        SubjectScope.NAMED_EMPLOYEE,
    ),
    (
        re.compile(
            r"\b(?:nhân viên|ai|người nào).*(?:có|sở hữu)\s+"
            r"(?:chứng chỉ|chứng nhận)\b",
            re.I,
        ),
        Domain.DIRECTORY,
        Intent.DIRECTORY_EMPLOYEE_BY_CERTIFICATE,
        SubjectScope.COMPANY,
    ),
    (
        re.compile(
            r"\b(?:liệt kê|danh sách|báo cáo).*(?:hợp đồng)"
            r".*(?:hết hạn|sắp hết hạn).*(?:\d+\s+ngày|sắp tới)\b",
            re.I,
        ),
        Domain.REPORTING,
        Intent.REPORT_CONTRACTS_EXPIRING,
        SubjectScope.COMPANY,
    ),
    (
        re.compile(r"\b(?:quên chấm công|thiếu lượt chấm công)\b", re.I),
        Domain.ATTENDANCE,
        Intent.ATTENDANCE_MISSING_PUNCH_COUNT,
        None,
    ),
    (
        re.compile(
            r"\b(?:số ngày làm việc|ngày công thực tế|actual work days)\b",
            re.I,
        ),
        Domain.ATTENDANCE,
        Intent.ATTENDANCE_ACTUAL_WORK_DAYS,
        None,
    ),
    (
        re.compile(r"\b(?:đi muộn|đi trễ)\b", re.I),
        Domain.ATTENDANCE,
        Intent.ATTENDANCE_LATE_COUNT,
        None,
    ),
    (
        re.compile(r"\blịch sử\s+(?:chấm công|check[- ]?in)\b", re.I),
        Domain.ATTENDANCE,
        Intent.ATTENDANCE_HISTORY,
        None,
    ),
    (
        re.compile(
            r"\b(?:ngày phép còn lại|còn (?:bao nhiêu|mấy) ngày phép|"
            r"số dư phép)\b",
            re.I,
        ),
        Domain.LEAVE,
        Intent.LEAVE_BALANCE,
        None,
    ),
    (
        re.compile(
            r"\b(?:trạng thái\s+đơn\s+nghỉ|"
            r"đơn\s+nghỉ.*(?:duyệt chưa|thế nào|trạng thái))",
            re.I,
        ),
        Domain.LEAVE,
        Intent.LEAVE_REQUEST_STATUS,
        None,
    ),
    (
        re.compile(r"\b(?:cấp trên|sếp|quản lý trực tiếp)\b", re.I),
        Domain.PROFILE,
        Intent.PROFILE_MANAGER,
        None,
    ),
    (
        re.compile(r"\b(?:phòng ban|thuộc phòng)\b", re.I),
        Domain.PROFILE,
        Intent.PROFILE_DEPARTMENT,
        None,
    ),
    (
        re.compile(r"\b(?:đơn vị công tác|công ty của tôi)\b", re.I),
        Domain.PROFILE,
        Intent.PROFILE_WORK_UNIT,
        None,
    ),
    (
        re.compile(r"\b(?:chức danh|vị trí công việc)\b", re.I),
        Domain.PROFILE,
        Intent.PROFILE_JOB_TITLE,
        None,
    ),
    (
        re.compile(r"\b(?:tài khoản ngân hàng|số tài khoản)\b", re.I),
        Domain.PROFILE,
        Intent.PROFILE_BANK_ACCOUNTS,
        None,
    ),
    (
        re.compile(r"\b(?:hợp đồng).*(?:hết hạn|kết thúc|bao giờ)\b", re.I),
        Domain.PROFILE,
        Intent.PROFILE_CONTRACT_EXPIRY,
        None,
    ),
    (
        re.compile(
            r"\b(?:trình độ học vấn|trình độ đào tạo|bằng cấp)\b",
            re.I,
        ),
        Domain.PROFILE,
        Intent.PROFILE_EDUCATION,
        None,
    ),
    (
        re.compile(
            r"\b[A-ZÀ-ỸĐ][A-Za-zÀ-ỹĐđ' -]{2,80}\s+"
            r"(?:ở|thuộc|làm việc tại)\s+"
            r"(?:cơ quan|phòng|đơn vị|ở đâu)\b",
        ),
        Domain.DIRECTORY,
        Intent.DIRECTORY_EMPLOYEE_DEPARTMENT,
        SubjectScope.NAMED_EMPLOYEE,
    ),
)


def refine_read_intent(
    query: str,
    classification: QueryClassification,
) -> QueryClassification:
    """Apply a small allowlisted semantic refinement after LLM classification."""
    if classification.intent is None:
        return classification
    for pattern, domain, intent, scope in _READ_REFINEMENTS:
        if pattern.search(query):
            subject = EntityResolver().extract_subject(query)
            if domain is Domain.PROFILE and subject.type is SubjectType.EMPLOYEE:
                domain = Domain.DIRECTORY
                scope = SubjectScope.NAMED_EMPLOYEE
            update: dict[str, object] = {
                "route": QueryRoute.DATA_QUERY,
                "domain": domain,
                "intent": intent,
                "operation": Operation.READ,
                "reason_code": "DETERMINISTIC_INTENT_REFINEMENT",
            }
            if scope is not None:
                update["scope"] = scope
            return classification.model_copy(update=update)
    return classification
