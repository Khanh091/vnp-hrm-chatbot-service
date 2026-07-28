from datetime import date

import pytest

from app.context.date_resolver import AmbiguousDateExpression, DateResolver
from app.routing.argument_resolver import ArgumentResolver
from app.routing.schemas import ToolSelection
from app.tools import build_tool_registry

TODAY = date(2026, 7, 27)


@pytest.mark.parametrize(
    ("query", "expected_from", "expected_to"),
    [
        ("hôm nay", date(2026, 7, 27), date(2026, 7, 27)),
        ("hôm qua", date(2026, 7, 26), date(2026, 7, 26)),
        ("ngày mai", date(2026, 7, 28), date(2026, 7, 28)),
        ("tháng này", date(2026, 7, 1), date(2026, 7, 31)),
        ("tháng trước", date(2026, 6, 1), date(2026, 6, 30)),
        ("quý II", date(2026, 4, 1), date(2026, 6, 30)),
        ("thứ hai tuần sau", date(2026, 8, 3), date(2026, 8, 3)),
    ],
)
def test_date_resolver(
    query: str,
    expected_from: date,
    expected_to: date,
) -> None:
    result = DateResolver().resolve(
        query,
        current_date=TODAY,
        timezone="Asia/Ho_Chi_Minh",
    )

    assert result is not None
    assert result.date_from == expected_from
    assert result.date_to == expected_to


def test_bare_weekday_is_ambiguous() -> None:
    with pytest.raises(AmbiguousDateExpression):
        DateResolver().resolve(
            "Cho tôi nghỉ thứ hai",
            current_date=TODAY,
            timezone="Asia/Ho_Chi_Minh",
        )


def test_argument_resolver_uses_code_date_and_rejects_trusted_fields() -> None:
    tool = build_tool_registry().get("leave_cancel_request")
    result = ArgumentResolver().resolve(
        ToolSelection(
            selected_tool=tool.name,
            confidence=0.95,
            extracted_arguments={"odoo_user_id": 999},
            reason_code="CANCEL_REQUEST",
        ),
        tool,
        query="Hủy đơn nghỉ LEAVE-00123",
        current_date=TODAY,
        timezone="Asia/Ho_Chi_Minh",
    )

    assert result.arguments["request_id"] == 123
    assert "odoo_user_id" not in result.arguments
    assert result.rejected_trusted_fields == ["odoo_user_id"]


def test_argument_resolver_does_not_guess_leave_type_id() -> None:
    tool = build_tool_registry().get("leave_create_request")
    result = ArgumentResolver().resolve(
        ToolSelection(
            selected_tool=tool.name,
            confidence=0.95,
            extracted_arguments={"leave_type_text": "Phép năm"},
            missing_arguments=["leave_type_id"],
            requires_clarification=True,
            clarification_question="Bạn muốn dùng loại nghỉ nào?",
            reason_code="CREATE_LEAVE",
        ),
        tool,
        query="Tạo đơn nghỉ phép năm ngày mai",
        current_date=TODAY,
        timezone="Asia/Ho_Chi_Minh",
    )

    assert "leave_type_id" not in result.arguments
    assert result.transient_entities["leave_type_text"].lower() == "phép năm"
    assert result.arguments["date_from"] == date(2026, 7, 28)
    assert result.arguments["date_to"] == date(2026, 7, 28)
