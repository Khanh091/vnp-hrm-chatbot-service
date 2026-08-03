from __future__ import annotations

from datetime import date
from typing import Any

from pydantic import BaseModel, ConfigDict

DATE_SLOT_NAMES = frozenset(
    {
        "date",
        "date_from",
        "date_to",
        "start_date",
        "end_date",
        "valid_on",
    }
)


class InvalidStructuredSelection(ValueError):
    pass


class ValidatedStructuredSelection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    answer_type: str
    field: str
    value: str
    display_label: str
    business_value: str | date


def validate_structured_selection(
    answer: dict[str, Any],
    *,
    expected_field: str | None,
    allowed_options: list[dict[str, Any]],
    metadata: dict[str, Any] | None = None,
) -> ValidatedStructuredSelection:
    answer_type = answer.get("answer_type")
    field = answer.get("field")
    value = answer.get("value")
    if (
        answer_type not in {"option_select", "date_select"}
        or not expected_field
        or field != expected_field
        or value is None
    ):
        raise InvalidStructuredSelection
    if answer_type == "option_select":
        matched = next(
            (
                option
                for option in allowed_options
                if str(option.get("value")) == str(value)
            ),
            None,
        )
        if matched is None:
            raise InvalidStructuredSelection
        label = str(matched.get("label") or "").strip()
        if not label:
            raise InvalidStructuredSelection
        business_value: str | date = str(value)
    else:
        if field not in DATE_SLOT_NAMES:
            raise InvalidStructuredSelection
        try:
            selected_date = date.fromisoformat(str(value))
        except ValueError as error:
            raise InvalidStructuredSelection from error
        constraints = metadata or {}
        minimum = constraints.get("min_date")
        maximum = constraints.get("max_date")
        if minimum and selected_date < date.fromisoformat(str(minimum)):
            raise InvalidStructuredSelection
        if maximum and selected_date > date.fromisoformat(str(maximum)):
            raise InvalidStructuredSelection
        label = selected_date.strftime("%d/%m/%Y")
        business_value = selected_date
    return ValidatedStructuredSelection(
        answer_type=answer_type,
        field=field,
        value=str(value),
        display_label=label,
        business_value=business_value,
    )
