from __future__ import annotations

import re
from datetime import date
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.context.date_resolver import AmbiguousDateExpression, DateResolver
from app.context.entity_resolver import EntityResolver
from app.routing.schemas import ToolSelection
from app.tools.definitions import ToolDefinition

_TRUSTED_FIELDS = {
    "odoo_user_id",
    "employee_id",
    "department_id",
    "company_id",
    "contract_type_id",
    "company_ids",
    "group_codes",
    "capabilities",
    "conversation_id",
    "timezone",
}
_CONTROL_FIELDS = {
    "scope",
    "route",
    "route_type",
    "intent",
    "domain",
    "operation",
}
_SERVER_FIELDS = {"idempotency_key"}
_QUESTIONS = {
    "date": "Bạn muốn xem dữ liệu của ngày nào?",
    "date_from": "Bạn muốn bắt đầu từ ngày nào?",
    "date_to": "Bạn muốn kết thúc vào ngày nào?",
    "leave_type_id": "Bạn muốn sử dụng loại nghỉ nào?",
    "reason": "Bạn muốn ghi lý do nghỉ là gì?",
    "request_id": "Bạn muốn xem trạng thái của đơn nghỉ nào?",
    "employee_id": "Bạn muốn tra cứu nhân viên nào?",
    "department_id": "Bạn muốn tra cứu phòng ban nào?",
}


class ArgumentResolution(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    arguments: dict[str, Any]
    missing_arguments: list[str] = Field(default_factory=list)
    ambiguous_arguments: list[str] = Field(default_factory=list)
    rejected_trusted_fields: list[str] = Field(default_factory=list)
    transient_entities: dict[str, Any] = Field(default_factory=dict)
    clarification_question: str | None = None


class ArgumentResolver:
    def __init__(
        self,
        date_resolver: DateResolver | None = None,
        entity_resolver: EntityResolver | None = None,
    ) -> None:
        self._date_resolver = date_resolver or DateResolver()
        self._entity_resolver = entity_resolver or EntityResolver()

    def resolve(
        self,
        selection: ToolSelection,
        tool: ToolDefinition,
        *,
        query: str,
        current_date: date,
        timezone: str,
        conversation_arguments: dict[str, Any] | None = None,
    ) -> ArgumentResolution:
        arguments = dict(conversation_arguments or {})
        extracted_arguments = dict(selection.extracted_arguments)
        rejected = sorted(_TRUSTED_FIELDS.intersection(extracted_arguments))
        for field in rejected:
            extracted_arguments.pop(field, None)
        arguments.update(extracted_arguments)
        for field in _CONTROL_FIELDS:
            arguments.pop(field, None)

        schema_fields = tool.argument_schema.model_fields
        transient: dict[str, Any] = {}
        for field in ("leave_type_text", "employee_name", "department_name"):
            value = arguments.pop(field, None)
            if value is not None:
                transient[field] = value

        entities = self._entity_resolver.extract(query)
        business = entities.business
        if business.leave_type_text and "leave_type_text" not in transient:
            transient["leave_type_text"] = business.leave_type_text
        if business.employee_name:
            transient["employee_name"] = business.employee_name
            if "name" in schema_fields:
                arguments.setdefault("name", business.employee_name)
        if business.employee_code:
            transient["employee_code"] = business.employee_code
            if "employee_code" in schema_fields:
                arguments.setdefault("employee_code", business.employee_code)
        if business.department_name:
            transient["department_name"] = business.department_name
            if "name" in schema_fields:
                arguments.setdefault("name", business.department_name)
        if business.contract_code:
            transient["contract_code"] = business.contract_code
        if business.reason and "reason" in schema_fields:
            arguments.setdefault("reason", business.reason)

        if "certificate_query" in schema_fields:
            certificate = re.search(
                r"(?:chứng\s+chỉ|chứng\s+nhận|certificate)\s+"
                r"(?P<value>[A-Za-z0-9][A-Za-z0-9 ._+/#-]{0,120})",
                query,
                re.IGNORECASE,
            )
            if certificate:
                value = re.sub(
                    r"\s+(?:nào|gì|của ai|không)\s*[?.!]*$",
                    "",
                    certificate.group("value").strip(),
                    flags=re.IGNORECASE,
                ).strip(" ?.!")
                if value:
                    arguments.setdefault("certificate_query", value)

        if "within_days" in schema_fields:
            within_days = re.search(
                r"\b(?:trong|sắp tới|tiếp theo)?\s*"
                r"(?P<days>\d{1,3})\s*ngày\s*"
                r"(?:tới|nữa|tiếp theo|sắp tới)?\b",
                query,
                re.IGNORECASE,
            )
            if within_days:
                arguments.setdefault(
                    "within_days",
                    int(within_days.group("days")),
                )

        if business.leave_request_code:
            transient["leave_request_code"] = business.leave_request_code
            # Only a plain numeric identifier is accepted by the current tool
            # contract. A LEAVE-* business code needs an allowlisted lookup.
            if (
                "request_id" in schema_fields
                and business.leave_request_code.isdigit()
            ):
                arguments.setdefault(
                    "request_id",
                    int(business.leave_request_code),
                )

        ambiguous = list(selection.ambiguous_arguments)
        try:
            resolved_date = self._date_resolver.resolve(
                query,
                current_date=current_date,
                timezone=timezone,
            )
        except AmbiguousDateExpression:
            resolved_date = None
            ambiguous.append("date")

        if resolved_date is not None:
            if "date" in schema_fields:
                if resolved_date.date_from == resolved_date.date_to:
                    arguments["date"] = resolved_date.date_from
                else:
                    ambiguous.append("date")
            if "date_from" in schema_fields:
                arguments["date_from"] = resolved_date.date_from
            if "date_to" in schema_fields:
                arguments["date_to"] = resolved_date.date_to
            if "year" in schema_fields:
                arguments.setdefault("year", resolved_date.date_from.year)

        if "year" in schema_fields:
            arguments.setdefault("year", current_date.year)

        missing = [
            name
            for name, field in schema_fields.items()
            if field.is_required()
            and name not in _SERVER_FIELDS
            and arguments.get(name) is None
        ]
        missing = list(dict.fromkeys([*selection.missing_arguments, *missing]))
        missing = [item for item in missing if item not in _SERVER_FIELDS]
        ambiguous = list(dict.fromkeys(ambiguous))
        question_field = (
            ambiguous[0] if ambiguous else missing[0] if missing else None
        )
        question = (
            _QUESTIONS.get(
                question_field,
                f"Bạn vui lòng cung cấp {question_field}.",
            )
            if question_field
            else None
        )
        return ArgumentResolution(
            arguments=arguments,
            missing_arguments=missing,
            ambiguous_arguments=ambiguous,
            rejected_trusted_fields=rejected,
            transient_entities=transient,
            clarification_question=question,
        )
