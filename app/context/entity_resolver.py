import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.context.entities import (
    BusinessEntities,
    EntityAmbiguity,
    ExtractedEntities,
    TemporalEntities,
)
from app.routing.schemas import SubjectScope


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
        re.IGNORECASE,
    )
    _EMPLOYEE = re.compile(
        r"\b(?:anh|chị|ông|bà|nhân viên)\s+"
        r"(?P<name>[A-ZÀ-Ỹ][\wÀ-ỹ]*(?:\s+[A-ZÀ-Ỹ][\wÀ-ỹ]*){1,5})",
    )
    _EMPLOYEE_CODE = re.compile(
        r"\b(?:mã nhân viên|mã nhân sự|mã nv)\s*[:#-]?\s*"
        r"(?P<code>[A-Z0-9][A-Z0-9._-]{1,30})\b",
        re.IGNORECASE,
    )
    _CONTRACT_CODE = re.compile(
        r"\b(?:hợp đồng|contract)\s*(?:mã|số)?\s*"
        r"(?P<code>[A-Z][A-Z0-9._/-]{2,40})\b",
        re.IGNORECASE,
    )
    _REASON = re.compile(
        r"\b(?:lý do|vì)\s*[:\-]?\s*(?P<reason>[^,.!?]{2,500})",
        re.IGNORECASE,
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

    def resolve(self, text: str) -> ResolvedEntities:
        request = self._REQUEST_CODE.search(text)
        employee = self._EMPLOYEE.search(text)
        scope = (
            SubjectScope.NAMED_EMPLOYEE
            if employee is not None
            else SubjectScope.COMPANY
            if re.search(r"\btoàn công ty\b", text, re.IGNORECASE)
            else SubjectScope.DEPARTMENT
            if re.search(r"\b(?:phòng|ban|đơn vị)\s+", text, re.IGNORECASE)
            else SubjectScope.SELF
        )
        leave_type = None
        leave_match = re.search(
            r"\b(phép năm|nghỉ ốm|nghỉ không lương|nghỉ thai sản)\b",
            text,
            re.IGNORECASE,
        )
        if leave_match is not None:
            leave_type = leave_match.group(1)
        return ResolvedEntities(
            employee_name=employee.group("name") if employee else None,
            leave_type_text=leave_type,
            request_code=request.group("code") if request else None,
            scope=scope,
        )
