from __future__ import annotations

import re

from app.routing.schemas import Domain, QueryClassification
from app.routing.taxonomy import Intent, Operation, QueryRoute

_READ_REFINEMENTS: tuple[
    tuple[re.Pattern[str], Domain, Intent],
    ...,
] = (
    (
        re.compile(r"\b(?:đi muộn|đi trễ)\b", re.IGNORECASE),
        Domain.ATTENDANCE,
        Intent.ATTENDANCE_LATE_COUNT,
    ),
    (
        re.compile(r"\blịch sử\s+(?:chấm công|check[- ]?in)\b", re.IGNORECASE),
        Domain.ATTENDANCE,
        Intent.ATTENDANCE_HISTORY,
    ),
    (
        re.compile(
            r"\b(?:ngày phép còn lại|còn (?:bao nhiêu|mấy) ngày phép|"
            r"số dư phép)\b",
            re.IGNORECASE,
        ),
        Domain.LEAVE,
        Intent.LEAVE_BALANCE,
    ),
    (
        re.compile(r"\b(?:cấp trên|sếp|quản lý trực tiếp)\b", re.IGNORECASE),
        Domain.PROFILE,
        Intent.PROFILE_MANAGER,
    ),
    (
        re.compile(r"\b(?:phòng ban|thuộc phòng)\b", re.IGNORECASE),
        Domain.PROFILE,
        Intent.PROFILE_DEPARTMENT,
    ),
    (
        re.compile(r"\b(?:đơn vị công tác|công ty của tôi)\b", re.IGNORECASE),
        Domain.PROFILE,
        Intent.PROFILE_WORK_UNIT,
    ),
    (
        re.compile(r"\b(?:chức danh|vị trí công việc)\b", re.IGNORECASE),
        Domain.PROFILE,
        Intent.PROFILE_JOB_TITLE,
    ),
    (
        re.compile(
            r"\b(?:hợp đồng).*(?:hết hạn|kết thúc|bao giờ)\b",
            re.IGNORECASE,
        ),
        Domain.PROFILE,
        Intent.PROFILE_CONTRACT_EXPIRY,
    ),
    (
        re.compile(
            r"\b(?:trình độ học vấn|trình độ đào tạo|bằng cấp)\b",
            re.IGNORECASE,
        ),
        Domain.PROFILE,
        Intent.PROFILE_EDUCATION,
    ),
)


def refine_read_intent(
    query: str,
    classification: QueryClassification,
) -> QueryClassification:
    """Apply a small allowlisted semantic refinement after LLM classification."""
    if classification.intent is None:
        return classification
    for pattern, domain, intent in _READ_REFINEMENTS:
        if pattern.search(query):
            return classification.model_copy(
                update={
                    "route": QueryRoute.DATA_QUERY,
                    "domain": domain,
                    "intent": intent,
                    "operation": Operation.READ,
                    "reason_code": "DETERMINISTIC_INTENT_REFINEMENT",
                }
            )
    return classification
