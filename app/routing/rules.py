from __future__ import annotations

import re
from dataclasses import dataclass

from app.routing.query_normalizer import QueryNormalizer
from app.routing.schemas import (
    Domain,
    NormalizedQuery,
    Operation,
    RouteType,
    RuleHints,
    SemanticHint,
)
from app.routing.taxonomy import Intent


@dataclass(frozen=True)
class SemanticRule:
    concept: str
    pattern: re.Pattern[str]
    candidate_intents: tuple[Intent, ...]
    confidence: float
    is_exclusive: bool = False


_SEMANTIC_RULES = (
    SemanticRule(
        concept="profile_self_declaration_status",
        pattern=re.compile(
            r"\b(?:trang thai|tinh trang)\b.{0,32}"
            r"\b(?:ho so tu khai|ho so khai bao|tu khai)\b"
        ),
        candidate_intents=(Intent.PROFILE_SELF_DECLARATION_STATUS,),
        confidence=0.99,
        is_exclusive=True,
    ),
    SemanticRule(
        concept="attendance_full_history",
        pattern=re.compile(
            r"\b(?:(?:toan bo|tat ca|day du) "
            r"(?:thong tin|du lieu|ban ghi) cham cong|"
            r"toan bo cham cong)\b"
        ),
        candidate_intents=(Intent.ATTENDANCE_HISTORY,),
        confidence=0.98,
        is_exclusive=True,
    ),
    SemanticRule(
        concept="attendance_unassigned_shift_worked_days",
        pattern=re.compile(
            r"\b(?:so ngay )?(?:khong (?:duoc )?phan ca|khong co ca) "
            r"(?:nhung |ma )?(?:co )?(?:di lam|cham cong)\b"
        ),
        candidate_intents=(Intent.ATTENDANCE_UNASSIGNED_SHIFT_WORKED_DAYS,),
        confidence=0.99,
        is_exclusive=True,
    ),
    SemanticRule(
        concept="attendance_no_attendance_days",
        pattern=re.compile(r"\b(?:so ngay )?(?:khong|chua) cham cong\b"),
        candidate_intents=(Intent.ATTENDANCE_NO_ATTENDANCE_DAYS,),
        confidence=0.99,
        is_exclusive=True,
    ),
    SemanticRule(
        concept="attendance_missing_punch",
        pattern=re.compile(
            r"\b(?:quen cham cong|thieu luot cham cong|"
            r"thieu check[- ]?in|thieu check[- ]?out)\b"
        ),
        candidate_intents=(Intent.ATTENDANCE_MISSING_PUNCH_COUNT,),
        confidence=0.99,
        is_exclusive=True,
    ),
    SemanticRule(
        concept="attendance_recorded_days",
        pattern=re.compile(
            r"\b(?:cham cong (?:duoc |bao nhieu |may )?ngay|"
            r"so ngay (?:co )?cham cong)\b"
        ),
        candidate_intents=(Intent.ATTENDANCE_RECORDED_DAYS,),
        confidence=0.99,
        is_exclusive=True,
    ),
    SemanticRule(
        concept="attendance_actual_work_days",
        pattern=re.compile(r"\b(?:ngay cong thuc te|so ngay lam viec)\b"),
        candidate_intents=(Intent.ATTENDANCE_ACTUAL_WORK_DAYS,),
        confidence=0.99,
        is_exclusive=True,
    ),
    SemanticRule(
        concept="leave_remaining_balance",
        pattern=re.compile(
            r"\b(?:so ngay phep con lai|ngay phep con lai|"
            r"con (?:bao nhieu|may) ngay phep)\b"
        ),
        candidate_intents=(Intent.LEAVE_BALANCE,),
        confidence=0.99,
        is_exclusive=True,
    ),
    SemanticRule(
        concept="profile_identity_document",
        pattern=re.compile(
            r"\b(?:cccd|cmnd|so can cuoc|"
            r"(?:ngay|noi) cap (?:cccd|cmnd|can cuoc))\b"
        ),
        candidate_intents=(Intent.PROFILE_IDENTITY,),
        confidence=0.99,
        is_exclusive=True,
    ),
    SemanticRule(
        concept="profile_bank_account",
        pattern=re.compile(r"\b(?:so tai khoan ngan hang|so tai khoan)\b"),
        candidate_intents=(Intent.PROFILE_BANK_ACCOUNTS,),
        confidence=0.99,
        is_exclusive=True,
    ),
    SemanticRule(
        concept="profile_party_union",
        pattern=re.compile(
            r"\b(?:dang vien|doan vien|the dang|ngay vao dang|"
            r"ngay ket nap dang|ngay vao doan|sinh hoat dang|"
            r"sinh hoat doan)\b"
        ),
        candidate_intents=(Intent.PROFILE_PARTY_UNION,),
        confidence=0.99,
        is_exclusive=True,
    ),
    SemanticRule(
        concept="profile_education",
        pattern=re.compile(
            r"\b(?:trinh do giao duc pho thong|hoc van|"
            r"trinh do chuyen mon cao nhat|hinh thuc dao tao|"
            r"chuyen nganh|co so dao tao|trinh do dao tao)\b"
        ),
        candidate_intents=(Intent.PROFILE_EDUCATION,),
        confidence=0.99,
        is_exclusive=True,
    ),
    SemanticRule(
        concept="profile_training_history",
        pattern=re.compile(
            r"\b(?:dao tao boi duong|lich su dao tao|"
            r"lich su khoa hoc|cam ket dao tao)\b"
        ),
        candidate_intents=(Intent.PROFILE_TRAINING_HISTORY,),
        confidence=0.96,
    ),
    SemanticRule(
        concept="profile_address",
        pattern=re.compile(
            r"\b(?:noi o hien nay|noi o hien tai|ho khau thuong tru|"
            r"que quan|noi sinh|dia chi hien tai)\b"
        ),
        candidate_intents=(Intent.PROFILE_ADDRESS,),
        confidence=0.99,
        is_exclusive=True,
    ),
    SemanticRule(
        concept="contract_expiry_or_validity",
        pattern=re.compile(
            r"\b(?:"
            r"hop dong(?:.{0,48})"
            r"(?:het han|con han|con hieu luc|"
            r"ngay ket thuc|bao gio het han)"
            r"|(?:da het|ngay ket thuc)(?:.{0,24})hop dong"
            r")\b"
        ),
        candidate_intents=(Intent.PROFILE_CONTRACT_EXPIRY,),
        confidence=0.99,
        is_exclusive=True,
    ),
    SemanticRule(
        concept="profile_identity_attributes",
        pattern=re.compile(
            r"\b(?:dan toc|quoc tich|ton giao|"
            r"tinh trang hon nhan)\b"
        ),
        candidate_intents=(Intent.PROFILE_IDENTITY,),
        confidence=0.96,
    ),
    SemanticRule(
        concept="profile_other_name",
        pattern=re.compile(r"\b(?:ten goi khac|ten khac|bi danh)\b"),
        candidate_intents=(Intent.PROFILE_BASIC,),
        confidence=0.98,
        is_exclusive=True,
    ),
    SemanticRule(
        concept="profile_certificate_issue",
        pattern=re.compile(
            r"\b(?:ngay|noi) cap (?:chung chi|chung nhan|"
            r"toeic|ielts|aws|pmp)\b"
        ),
        candidate_intents=(Intent.PROFILE_CERTIFICATES,),
        confidence=0.96,
    ),
    SemanticRule(
        concept="directory_employee_workplace",
        pattern=re.compile(
            r"\b(?:o co quan nao|thuoc co quan nao|"
            r"dia chi co quan|don vi cong tac|lam o dau)\b"
        ),
        candidate_intents=(Intent.DIRECTORY_EMPLOYEE_DEPARTMENT,),
        confidence=0.95,
    ),
    SemanticRule(
        concept="directory_departments",
        pattern=re.compile(
            r"\b(?:(?:danh sach|liet ke)(?: cac)? "
            r"(?:phong ban|phong|don vi|co quan)|"
            r"(?:co nhung|co bao nhieu) (?:phong ban|phong|don vi))\b"
        ),
        candidate_intents=(Intent.DIRECTORY_DEPARTMENTS,),
        confidence=0.99,
        is_exclusive=True,
    ),
    SemanticRule(
        concept="directory_employee_in_actor_department",
        pattern=re.compile(
            r"\b(?:co (?:o|thuoc) (?:phong ban|phong|don vi) "
            r"(?:cua )?toi khong|co cung phong (?:voi )?toi khong)\b"
        ),
        candidate_intents=(Intent.DIRECTORY_EMPLOYEE_IN_DEPARTMENT,),
        confidence=0.99,
        is_exclusive=True,
    ),
    SemanticRule(
        concept="department_employee_list",
        pattern=re.compile(
            r"\b(?:"
            r"(?:danh sach|liet ke)(?:.{0,20})nhan vien"
            r"(?:.{0,28})(?:phong|ban|don vi)"
            r"|nhan vien(?:.{0,28})(?:phong|ban|don vi)"
            r"|nhan vien\s+[A-Z0-9]{2,}(?:\s+[a-z]+){1,6}"
            r")\b"
        ),
        candidate_intents=(Intent.DIRECTORY_DEPARTMENT_EMPLOYEES,),
        confidence=0.99,
        is_exclusive=True,
    ),
    SemanticRule(
        concept="profile_health",
        pattern=re.compile(
            r"\b(?:thong tin suc khoe|tinh trang suc khoe|suc khoe|"
            r"nhom mau|chieu cao|can nang|kham suc khoe|tiem chung)\b"
        ),
        candidate_intents=(Intent.PROFILE_HEALTH,),
        confidence=0.98,
        is_exclusive=True,
    ),
    SemanticRule(
        concept="profile_family_relations",
        pattern=re.compile(
            r"\b(?:quan he gia dinh|nguoi than|than nhan|"
            r"me (?:de|ruot|cua)|cha (?:de|ruot|cua)|"
            r"bo (?:de|ruot|cua)|vo chong|con cai)\b"
        ),
        candidate_intents=(Intent.PROFILE_FAMILY_RELATIONS,),
        confidence=0.97,
        is_exclusive=True,
    ),
    SemanticRule(
        concept="profile_personal_background",
        pattern=re.compile(
            r"\b(?:ly lich ban than|lich su ban than|"
            r"than nhan nuoc ngoai|quan he nuoc ngoai|"
            r"hoan canh ca nhan)\b"
        ),
        candidate_intents=(Intent.PROFILE_PERSONAL_BACKGROUND,),
        confidence=0.96,
        is_exclusive=True,
    ),
    SemanticRule(
        concept="profile_family_economy",
        pattern=re.compile(
            r"\b(?:kinh te gia dinh|nguon thu nhap khac|"
            r"thu nhap khai bao|dat san xuat kinh doanh|"
            r"tai san (?:san xuat|kinh doanh))\b"
        ),
        candidate_intents=(Intent.PROFILE_FAMILY_ECONOMY,),
        confidence=0.98,
        is_exclusive=True,
    ),
    SemanticRule(
        concept="profile_primary_assigned_work",
        pattern=re.compile(
            r"\b(?:cong viec chinh (?:duoc giao|dang lam)|"
            r"nhiem vu chinh duoc giao)\b"
        ),
        candidate_intents=(Intent.PROFILE_EMPLOYMENT,),
        confidence=0.98,
        is_exclusive=True,
    ),
)

_CREATE = re.compile(
    r"(?:^|\b(?:hay|giup toi|toi muon|toi)\s+)"
    r"(?:tao|them|bo sung|khai them|dang ky|lap|gui yeu cau)\b",
)
_UPDATE = re.compile(r"\b(?:sua|cap nhat|dieu chinh|chinh lai|doi|thay)\b")
_DELETE = re.compile(r"\b(?:xoa|go|bo(?!\s+sung\b))\b")
_CANCEL = re.compile(r"\b(?:huy|rut)(?:\s+(?:don|yeu cau|chung tu))?\b")
_LEAVE_CONTEXT = re.compile(r"\b(?:don nghi|nghi phep|xin nghi|phep nam)\b")
_SELF = re.compile(r"\b(?:toi|cua toi)\b")
_DEPARTMENT = re.compile(r"\b(?:phong|ban|don vi)\s+[a-z0-9]")
_COMPANY = re.compile(r"\b(?:toan cong ty|cong ty)\b")
_NAMED_EMPLOYEE = re.compile(
    r"\b[A-ZÀ-ỸĐ][\wÀ-ỹĐđ'-]+"
    r"(?:\s+[A-ZÀ-ỸĐ][\wÀ-ỹĐđ'-]+){1,5}\b"
)
_ASCII_NAMED_CONTEXT = re.compile(
    r"\b[a-z][a-z'-]+(?:\s+[a-z][a-z'-]+){2,5}\s+"
    r"(?:o|thuoc|lam|da|co|vao)\b"
)
_NAMED_DEPARTMENT_ACRONYM = re.compile(
    r"\bnhân\s+viên\s+[A-ZÀ-ỸĐ0-9]{2,}"
    r"(?:\s+[\wÀ-ỹĐđ/-]+){1,6}\s*[?.!]*$"
)


def _as_query(value: NormalizedQuery | str) -> NormalizedQuery:
    if isinstance(value, NormalizedQuery):
        if value.folded_text:
            return value
        return value.model_copy(
            update={"folded_text": QueryNormalizer.fold(value.normalized_text)}
        )
    return QueryNormalizer().normalize(value)


def infer_rule_hints(query: NormalizedQuery | str) -> RuleHints:
    """Produce pre-classification signals; never select a tool or technical ID."""

    normalized = _as_query(query)
    folded = normalized.folded_text
    semantic_hints = tuple(
        SemanticHint(
            concept=rule.concept,
            candidate_intents=rule.candidate_intents,
            confidence=rule.confidence,
            matched_text=match.group(0),
            is_exclusive=rule.is_exclusive,
        )
        for rule in _SEMANTIC_RULES
        if (match := rule.pattern.search(folded)) is not None
    )
    acronym_department = _NAMED_DEPARTMENT_ACRONYM.search(normalized.original_text)
    if acronym_department is not None and not any(
        hint.concept == "department_employee_list" for hint in semantic_hints
    ):
        semantic_hints = (
            *semantic_hints,
            SemanticHint(
                concept="department_employee_list",
                candidate_intents=(Intent.DIRECTORY_DEPARTMENT_EMPLOYEES,),
                confidence=0.99,
                matched_text=acronym_department.group(0),
                is_exclusive=True,
            ),
        )
    exclusive_intents = {
        intent
        for hint in semantic_hints
        if hint.is_exclusive
        for intent in hint.candidate_intents
    }

    operation: Operation | None = None
    reason_code: str | None = None
    if _CANCEL.search(folded) and _LEAVE_CONTEXT.search(folded):
        operation = Operation.CANCEL
        reason_code = "EXPLICIT_CANCEL_ACTION"
    elif _DELETE.search(folded):
        operation = Operation.DELETE
        reason_code = "EXPLICIT_DELETE_ACTION"
    elif _UPDATE.search(folded):
        operation = Operation.UPDATE
        reason_code = "EXPLICIT_UPDATE_ACTION"
    elif _CREATE.search(folded):
        operation = Operation.CREATE
        reason_code = "EXPLICIT_CREATE_ACTION"
    elif len(exclusive_intents) > 1:
        reason_code = "CONFLICTING_RULE_HINTS"

    domain_signals = tuple(
        dict.fromkeys(
            Domain(intent.value.split(".", 1)[0])
            for hint in semantic_hints
            for intent in hint.candidate_intents
            if intent.value.split(".", 1)[0] in {item.value for item in Domain}
        )
    )
    if operation is not None and _LEAVE_CONTEXT.search(folded):
        domain_signals = tuple(dict.fromkeys((*domain_signals, Domain.LEAVE)))

    self_reference = bool(_SELF.search(folded))
    named_reference = bool(
        _NAMED_EMPLOYEE.search(normalized.original_text)
        or (not self_reference and _ASCII_NAMED_CONTEXT.search(folded))
    )
    department_reference = bool(_DEPARTMENT.search(folded) or acronym_department)
    company_reference = bool(_COMPANY.search(folded))

    return RuleHints(
        route_hint=(RouteType.TRANSACTION if operation is not None else None),
        domain_hint=domain_signals[0] if len(domain_signals) == 1 else None,
        operation_hint=operation,
        confidence=0.9 if operation is not None else 0.0,
        reason_code=reason_code,
        self_reference=self_reference,
        named_employee_reference=named_reference,
        department_reference=department_reference,
        company_reference=company_reference,
        operation_signals=(operation,) if operation is not None else (),
        domain_signals=domain_signals,
        semantic_hints=semantic_hints,
    )
