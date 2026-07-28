from datetime import date

from app.routing.argument_resolver import ArgumentResolution
from app.routing.schemas import (
    Domain,
    Operation,
    QueryClassification,
    RouteType,
    ToolCandidate,
    ToolSelection,
)
from app.routing.tool_selector import ToolSelector
from app.routing.validator import ToolSelectionValidator
from app.tools import build_tool_registry
from tests.conftest import build_settings


def validate(
    tool_name: str,
    arguments: dict[str, object],
    *,
    confidence: float = 0.95,
    domain: Domain = Domain.LEAVE,
    route: RouteType = RouteType.STRUCTURED_QUERY,
    rejected: list[str] | None = None,
):
    registry = build_tool_registry()
    tool = registry.get(tool_name)
    candidate = ToolCandidate(
        tool_name=tool.name,
        domain=Domain(tool.domain.value),
        capability=tool.capability,
        operation=Operation(tool.operation.value),
        score=0.92,
        rank=1,
    )
    selector = ToolSelector(None, registry)  # type: ignore[arg-type]
    contexts = selector.build_candidate_contexts([candidate])
    return ToolSelectionValidator(registry, build_settings()).validate(
        ToolSelection(
            selected_tool=tool.name,
            confidence=confidence,
            reason_code="TEST_SELECTION",
        ),
        ArgumentResolution(
            arguments=arguments,
            rejected_trusted_fields=rejected or [],
        ),
        classification=QueryClassification(
            route_type=route,
            primary_domain=domain,
            operation_hint=Operation(tool.operation.value),
            confidence=0.95,
        ),
        candidates=contexts,
    )


def test_valid_read_can_execute() -> None:
    result = validate("leave_get_balance", {"year": 2026})

    assert result.valid is True
    assert result.can_execute is True
    assert result.requires_confirmation is False


def test_low_confidence_is_blocked() -> None:
    result = validate(
        "leave_get_balance",
        {"year": 2026},
        confidence=0.5,
    )

    assert result.can_execute is False
    assert any(
        issue.code == "SELECTION_CONFIDENCE_TOO_LOW"
        for issue in result.errors
    )


def test_domain_and_route_mismatch_are_blocked() -> None:
    result = validate(
        "leave_get_balance",
        {"year": 2026},
        domain=Domain.ATTENDANCE,
        route=RouteType.TRANSACTION,
    )

    codes = {issue.code for issue in result.errors}
    assert {"DOMAIN_MISMATCH", "ROUTE_MISMATCH"} <= codes


def test_extra_argument_is_blocked() -> None:
    result = validate(
        "leave_get_balance",
        {"year": 2026, "unexpected": True},
    )

    assert result.valid is False
    assert any(issue.code == "INVALID_ARGUMENT" for issue in result.errors)


def test_trusted_override_is_blocked() -> None:
    result = validate(
        "leave_get_balance",
        {"year": 2026},
        rejected=["odoo_user_id"],
    )

    assert any(issue.code == "TRUSTED_FIELD_REJECTED" for issue in result.errors)


def test_write_requires_confirmation_and_gets_server_idempotency_key() -> None:
    result = validate(
        "leave_cancel_request",
        {"request_id": 12},
        route=RouteType.TRANSACTION,
    )

    assert result.valid is True
    assert result.can_execute is False
    assert result.requires_confirmation is True
    assert result.normalized_arguments["idempotency_key"].startswith("chat-")


def test_invalid_date_range_is_blocked() -> None:
    result = validate(
        "leave_get_history",
        {
            "date_from": date(2026, 7, 20),
            "date_to": date(2026, 7, 1),
        },
    )

    assert result.valid is False
    assert any(issue.code == "INVALID_ARGUMENT" for issue in result.errors)
