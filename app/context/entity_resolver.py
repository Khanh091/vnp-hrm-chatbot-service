import re

from pydantic import BaseModel, ConfigDict

from app.routing.schemas import SubjectScope


class ResolvedEntities(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    employee_name: str | None = None
    department_name: str | None = None
    leave_type_text: str | None = None
    request_code: str | None = None
    contract_code: str | None = None
    scope: SubjectScope = SubjectScope.SELF


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
