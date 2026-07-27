import pytest
from pydantic import ValidationError

from app.tools import build_tool_registry
from app.tools.definitions import Domain, RouteType
from app.tools.registry import DuplicateToolError, ToolNotFoundError, ToolRegistry


def test_duplicate_tool_is_rejected() -> None:
    tool = build_tool_registry().get("profile_get_summary")
    registry = ToolRegistry([tool])

    with pytest.raises(DuplicateToolError):
        registry.register(tool)


def test_missing_tool_is_rejected() -> None:
    with pytest.raises(ToolNotFoundError):
        build_tool_registry().get("not_registered")


def test_registry_returns_immutable_snapshots() -> None:
    registry = build_tool_registry()
    snapshot = registry.list_all()

    assert isinstance(snapshot, tuple)
    with pytest.raises(ValidationError):
        snapshot[0].name = "changed"
    assert registry.list_all()[0].name == "profile_get_summary"


def test_registry_filters_without_exposing_internal_collection() -> None:
    registry = build_tool_registry()

    leave_commands = registry.filter(
        domain=Domain.LEAVE,
        route_type=RouteType.COMMAND,
        enabled=True,
    )

    assert tuple(tool.name for tool in leave_commands) == (
        "leave_create_request",
        "leave_update_request",
        "leave_cancel_request",
    )
    assert len(registry.list_by_domain(Domain.PROFILE)) == 11
