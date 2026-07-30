from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.context.entities import (
    BusinessEntities,
    EntityAmbiguity,
    ExtractedEntities,
    SubjectMention,
    TemporalEntities,
)
from app.routing.schemas import SubjectScope
from app.routing.taxonomy import SubjectType


class ResolvedEntities(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    employee_name: str | None = None
    department_name: str | None = None
    leave_type_text: str | None = None
    request_code: str | None = None
    contract_code: str | None = None
    scope: SubjectScope = SubjectScope.SELF


class EntityOption(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    value: int = Field(gt=0)
    label: str = Field(min_length=1, max_length=300)


class BusinessEntityResolver:
    @staticmethod
    def leave_type_options(data: Any) -> list[EntityOption]:
        if isinstance(data, dict):
            for key in ("leave_types", "items", "data", "result"):
                nested = data.get(key)
                if isinstance(nested, list):
                    data = nested
                    break
        if not isinstance(data, list):
            return []
        options: list[EntityOption] = []
        for item in data:
            if not isinstance(item, dict):
                continue
            value = (
                item.get("id")
                or item.get("value")
                or item.get("leave_type_id")
            )
            label = (
                item.get("name")
                or item.get("label")
                or item.get("display_name")
            )
            if isinstance(value, int) and isinstance(label, str):
                options.append(EntityOption(value=value, label=label))
        return options

    @staticmethod
    def match_leave_type(
        text: str,
        options: list[EntityOption],
    ) -> EntityOption | None:
        normalized = " ".join(text.casefold().split())
        matches = [
            option
            for option in options
            if " ".join(option.label.casefold().split()) == normalized
        ]
        return matches[0] if len(matches) == 1 else None


class EntityResolver:
    _REQUEST_CODE = re.compile(
        r"\b(?:đơn(?:\s+nghỉ)?|yêu cầu)\s*(?:mã|số)?\s*"
        r"(?P<code>(?:LEAVE-)?\d+)\b",
        re.I,
    )
    _EMPLOYEE = re.compile(
        r"\b(?:anh|chị|ông|bà|nhân viên)\s+"
        r"(?P<name>[A-ZÀ-ỸĐ][\wÀ-ỹĐđ'-]*"
        r"(?:\s+[A-ZÀ-ỸĐ][\wÀ-ỹĐđ'-]*){1,5})",
    )
    _BARE_EMPLOYEE = re.compile(
        r"\b(?P<name>[A-ZÀ-ỸĐ][\wÀ-ỹĐđ'-]*"
        r"(?:\s+[A-ZÀ-ỸĐ][\wÀ-ỹĐđ'-]*){1,5})"
        r"\s+(?:ở|thuộc|làm việc)\b",
    )
    _PROFILE_EMPLOYEE = re.compile(
        r"(?:\bcủa\s+|\b)"
        r"(?P<name>[A-ZÀ-ỸĐ][\wÀ-ỹĐđ'-]*"
        r"(?:\s+[A-ZÀ-ỸĐ][\wÀ-ỹĐđ'-]*){1,5})"
        r"\s+(?:ở|thuộc|làm việc|vào|đã|có|được)\b",
    )
    _POSSESSIVE_EMPLOYEE = re.compile(
        r"\bcủa\s+(?P<name>[A-ZÀ-ỸĐ][\wÀ-ỹĐđ'-]*"
        r"(?:\s+[A-ZÀ-ỸĐ][\wÀ-ỹĐđ'-]*){1,5})\s*[?.!]*$",
    )
    _DEPARTMENT = re.compile(
        r"\b(?:phòng|ban|đơn vị)\s+"
        r"(?P<name>[A-ZÀ-ỸĐ][\wÀ-ỹĐđ]*(?:\s+[\wÀ-ỹĐđ/-]+){0,8})",
        re.I,
    )
    _EMPLOYEE_CODE = re.compile(
        r"\b(?:mã nhân viên|mã nhân sự|mã nv|nhân viên mã)"
        r"\s*[:#-]?\s*"
        r"(?P<code>[A-Z0-9][A-Z0-9._-]{1,30})\b",
        re.I,
    )
    _CONTRACT_CODE = re.compile(
        r"\b(?:hợp đồng|contract)\s*(?:mã|số)?\s*"
        r"(?P<code>[A-Z][A-Z0-9._/-]{2,40})\b",
        re.I,
    )
    _REASON = re.compile(
        r"\b(?:lý do|vì)\s*[:\-]?\s*(?P<reason>[^,.!?]{2,500})",
        re.I,
    )

    def extract(self, text: str) -> ExtractedEntities:
        resolved = self.resolve(text)
        employee_code = self._EMPLOYEE_CODE.search(text)
        contract_code = self._CONTRACT_CODE.search(text)
        reason = self._REASON.search(text)
        normalized = " ".join(text.casefold().split())
        temporal_expression = re.search(
            r"\b("
            r"hôm nay|hôm qua|ngày mai|"
            r"tuần này|tuần trước|tuần sau|"
            r"tháng này|tháng trước|tháng sau|"
            r"năm nay|năm trước|"
            r"quý\s*(?:i{1,3}|iv)|"
            r"thứ hai tuần sau|"
            r"\d{1,2}/\d{1,2}/\d{4}"
            r")\b",
            normalized,
        )
        year_match = re.search(r"\b(19\d{2}|20\d{2}|21\d{2})\b", normalized)
        quarter_match = re.search(r"\bquý\s*(i{1,3}|iv)\b", normalized)
        ambiguous_match = re.search(
            r"\b(thứ hai|cuối tháng|đầu tuần|ngày đó)\b",
            normalized,
        )
        quarter = (
            {"i": 1, "ii": 2, "iii": 3, "iv": 4}[
                quarter_match.group(1)
            ]
            if quarter_match
            else None
        )
        return ExtractedEntities(
            temporal=TemporalEntities(
                date=(
                    temporal_expression.group(0)
                    if temporal_expression
                    else None
                ),
                year=int(year_match.group(1)) if year_match else None,
                quarter=quarter,
                time_range=(
                    normalized
                    if re.search(r"\btừ\b.+\bđến\b", normalized)
                    else None
                ),
            ),
            business=BusinessEntities(
                employee_name=resolved.employee_name,
                employee_code=(
                    employee_code.group("code") if employee_code else None
                ),
                department_name=resolved.department_name,
                leave_type_text=resolved.leave_type_text,
                leave_request_code=resolved.request_code,
                contract_code=(
                    contract_code.group("code") if contract_code else None
                ),
                reason=reason.group("reason").strip() if reason else None,
            ),
            ambiguities=(
                [
                    EntityAmbiguity(
                        field="date",
                        expression=ambiguous_match.group(1),
                        reason_code="AMBIGUOUS_DATE_EXPRESSION",
                    )
                ]
                if ambiguous_match
                and not (
                    ambiguous_match.group(1) == "thứ hai"
                    and "thứ hai tuần sau" in normalized
                )
                else []
            ),
        )

    def extract_subject(self, text: str) -> SubjectMention:
        normalized = " ".join(text.strip().split())
        employee_code = self._EMPLOYEE_CODE.search(normalized)
        employee = self._EMPLOYEE.search(normalized)
        bare_employee = self._BARE_EMPLOYEE.search(normalized)
        department = self._DEPARTMENT.search(normalized)
        profile_employee = self._PROFILE_EMPLOYEE.search(normalized)
        possessive_employee = self._POSSESSIVE_EMPLOYEE.search(normalized)
        recency: Literal["latest", "previous", "first", "last"] | None = (
            "latest"
            if re.search(r"\b(?:gần nhất|mới nhất)\b", normalized, re.I)
            else "previous"
            if re.search(r"\b(?:trước đó|trước)\b", normalized, re.I)
            else "first"
            if re.search(r"\bđầu tiên\b", normalized, re.I)
            else "last"
            if re.search(r"\bcuối cùng\b", normalized, re.I)
            else None
        )
        ordinal_match = re.search(
            r"\b(?:thứ|số)\s*(?P<ordinal>\d{1,3})\b",
            normalized,
            re.I,
        )
        ordinal_word_match = re.search(
            r"\bđơn(?:\s+nghỉ)?\s+thứ\s+"
            r"(?P<ordinal>hai|ba|tư|bốn|năm|sáu|bảy|tám|chín|mười)\b",
            normalized,
            re.I,
        )
        date_reference_match = re.search(
            r"\bđơn(?:\s+nghỉ)?\s+ngày\s+"
            r"(?P<day>\d{1,2})[/-](?P<month>\d{1,2})"
            r"(?:[/-](?P<year>\d{4}))?\b",
            normalized,
            re.I,
        )
        ordinal_words = {
            "hai": 2,
            "ba": 3,
            "tư": 4,
            "bốn": 4,
            "năm": 5,
            "sáu": 6,
            "bảy": 7,
            "tám": 8,
            "chín": 9,
            "mười": 10,
        }
        employee_name = (
            employee.group("name")
            if employee
            else bare_employee.group("name")
            if bare_employee
            else profile_employee.group("name")
            if profile_employee
            else possessive_employee.group("name")
            if possessive_employee
            else None
        )
        subject_type = (
            SubjectType.EMPLOYEE
            if employee_name or employee_code
            else SubjectType.DEPARTMENT
            if department
            else SubjectType.SELF
            if re.search(r"\b(?:tôi|của tôi|đơn)\b", normalized, re.I)
            else SubjectType.GENERAL
        )
        return SubjectMention(
            type=subject_type,
            employee_name=employee_name,
            employee_code=(
                employee_code.group("code") if employee_code else None
            ),
            department_name=(
                department.group("name").strip() if department else None
            ),
            date_reference=(
                "/".join(
                    part
                    for part in (
                        date_reference_match.group("day"),
                        date_reference_match.group("month"),
                        date_reference_match.group("year"),
                    )
                    if part
                )
                if date_reference_match
                else None
            ),
            ordinal_reference=(
                int(ordinal_match.group("ordinal"))
                if ordinal_match
                else ordinal_words[
                    ordinal_word_match.group("ordinal").casefold()
                ]
                if ordinal_word_match
                else 1
                if recency == "first"
                else None
            ),
            recency_reference=recency,
        )

    def resolve(self, text: str) -> ResolvedEntities:
        request = self._REQUEST_CODE.search(text)
        employee = (
            self._EMPLOYEE.search(text)
            or self._BARE_EMPLOYEE.search(text)
            or self._PROFILE_EMPLOYEE.search(text)
            or self._POSSESSIVE_EMPLOYEE.search(text)
        )
        department = self._DEPARTMENT.search(text)
        scope = (
            SubjectScope.NAMED_EMPLOYEE
            if employee is not None
            else SubjectScope.COMPANY
            if re.search(r"\btoàn công ty\b", text, re.I)
            else SubjectScope.DEPARTMENT
            if department is not None
            else SubjectScope.SELF
        )
        leave_match = re.search(
            r"\b(phép năm|nghỉ ốm|nghỉ không lương|nghỉ thai sản)\b",
            text,
            re.I,
        )
        return ResolvedEntities(
            employee_name=employee.group("name") if employee else None,
            department_name=(
                department.group("name").strip() if department else None
            ),
            leave_type_text=leave_match.group(1) if leave_match else None,
            request_code=request.group("code") if request else None,
            scope=scope,
        )
