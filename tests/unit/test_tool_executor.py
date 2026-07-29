import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any

import httpx
import pytest

from app.integrations.odoo.client import OdooClient
from app.tools import build_tool_registry
from app.tools.definitions import TrustedExecutionContext
from app.tools.executor import ToolExecutor
from app.tools.registry import ToolRegistry
from tests.conftest import build_settings

Handler = Callable[[httpx.Request], Awaitable[httpx.Response]]


def envelope(
    *,
    success: bool = True,
    code: str = "SUCCESS",
    message: str = "Success",
    data: Any = None,
) -> bytes:
    return json.dumps(
        {
            "success": success,
            "code": code,
            "message": message,
            "data": data,
            "meta": {
                "request_id": "tool-request-1",
                "timestamp": "2026-07-27T00:00:00Z",
            },
        }
    ).encode()


def context() -> TrustedExecutionContext:
    return TrustedExecutionContext(
        odoo_user_id=42,
        request_id="tool-request-1",
    )


async def run_with_handler(
    handler: Handler,
    tool_name: str,
    arguments: dict[str, Any],
    *,
    confirmed: bool = False,
    registry: ToolRegistry | None = None,
):
    client = OdooClient(
        build_settings(),
        transport=httpx.MockTransport(handler),
    )
    try:
        return await ToolExecutor(
            registry or build_tool_registry(),
            client,
        ).execute(
            tool_name,
            arguments,
            context=context(),
            confirmed=confirmed,
        )
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_disabled_tool_is_not_called() -> None:
    called = False

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(200)

    disabled = build_tool_registry().get("profile_get_summary").model_copy(
        update={"enabled": False}
    )
    result = await run_with_handler(
        handler,
        disabled.name,
        {},
        registry=ToolRegistry([disabled]),
    )

    assert result.error_code == "TOOL_DISABLED"
    assert called is False


@pytest.mark.asyncio
async def test_invalid_argument_schema_is_not_called() -> None:
    called = False

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(200)

    result = await run_with_handler(
        handler,
        "attendance_get_daily",
        {"date": "not-a-date"},
    )

    assert result.error_code == "INVALID_ARGUMENTS"
    assert called is False


@pytest.mark.asyncio
async def test_trusted_user_context_is_injected_and_endpoint_is_allowlisted() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/hrm-chatbot/v1/attendance/current/daily"
        assert request.method == "POST"
        assert request.headers["X-Request-ID"] == "tool-request-1"
        assert json.loads(request.content) == {
            "date": "2026-07-27",
            "odoo_user_id": 42,
        }
        return httpx.Response(
            200,
            content=envelope(data={"employee_id": 7, "state": "present"}),
        )

    result = await run_with_handler(
        handler,
        "attendance_get_daily",
        {"date": "2026-07-27"},
    )

    assert result.success is True
    assert result.data["employee_id"] == 7


@pytest.mark.asyncio
async def test_scope_control_field_is_not_a_business_argument() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["odoo_user_id"] == "42"
        assert "scope" not in request.url.params
        return httpx.Response(
            200,
            content=envelope(data={"department": {"name": "Phòng CNTT"}}),
        )

    result = await run_with_handler(
        handler,
        "profile_get_employment",
        {"scope": "self"},
    )

    assert result.success is True


@pytest.mark.asyncio
async def test_input_cannot_override_trusted_user_id() -> None:
    called = False

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(200)

    result = await run_with_handler(
        handler,
        "profile_get_summary",
        {"odoo_user_id": 999},
    )

    assert result.error_code == "TRUSTED_FIELD_INJECTION"
    assert called is False


@pytest.mark.asyncio
async def test_write_tool_requires_confirmation() -> None:
    called = False

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(200)

    result = await run_with_handler(
        handler,
        "leave_cancel_request",
        {"request_id": 12, "idempotency_key": "cancel-12"},
    )

    assert result.error_code == "CONFIRMATION_REQUIRED"
    assert called is False


@pytest.mark.asyncio
async def test_confirmed_write_renders_only_validated_path_argument() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/hrm-chatbot/v1/leave/requests/12/cancel"
        assert json.loads(request.content) == {
            "idempotency_key": "cancel-12",
            "odoo_user_id": 42,
        }
        return httpx.Response(
            200,
            content=envelope(data={"request_id": 12, "state": "cancel"}),
        )

    result = await run_with_handler(
        handler,
        "leave_cancel_request",
        {"request_id": 12, "idempotency_key": "cancel-12"},
        confirmed=True,
    )

    assert result.success is True


@pytest.mark.asyncio
async def test_leave_create_requires_reason_before_odoo_call() -> None:
    called = False

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(200)

    result = await run_with_handler(
        handler,
        "leave_create_request",
        {
            "date_from": "2026-07-30",
            "date_to": "2026-08-02",
            "leave_type_id": 3,
            "request_unit": "day",
            "idempotency_key": "create-without-reason",
        },
        confirmed=True,
    )

    assert result.error_code == "INVALID_ARGUMENTS"
    assert called is False


@pytest.mark.asyncio
async def test_confirmed_leave_create_matches_odoo_contract() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert payload == {
            "date_from": "2026-07-30",
            "date_to": "2026-08-02",
            "leave_type_id": 3,
            "request_unit": "day",
            "half_day_period": None,
            "time_from": None,
            "time_to": None,
            "reason": "Việc cá nhân",
            "idempotency_key": "create-with-reason",
            "odoo_user_id": 42,
        }
        return httpx.Response(
            200,
            content=envelope(
                data={"request_id": 100, "state": "draft"},
            ),
        )

    result = await run_with_handler(
        handler,
        "leave_create_request",
        {
            "date_from": "2026-07-30",
            "date_to": "2026-08-02",
            "leave_type_id": 3,
            "request_unit": "day",
            "reason": "Việc cá nhân",
            "idempotency_key": "create-with-reason",
        },
        confirmed=True,
    )

    assert result.success is True


@pytest.mark.asyncio
async def test_odoo_business_error_becomes_typed_failure() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400,
            content=envelope(
                success=False,
                code="INSUFFICIENT_LEAVE_BALANCE",
                message="Insufficient leave balance",
            ),
        )

    result = await run_with_handler(
        handler,
        "leave_get_balance",
        {"year": 2026},
    )

    assert result.success is False
    assert result.error_code == "INSUFFICIENT_LEAVE_BALANCE"
    assert result.error_message == "Insufficient leave balance"


@pytest.mark.asyncio
async def test_odoo_access_denied_code_is_preserved() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            403,
            content=envelope(
                success=False,
                code="ACCESS_DENIED",
                message="Forbidden",
            ),
        )

    result = await run_with_handler(
        handler,
        "profile_get_contact",
        {},
    )

    assert result.success is False
    assert result.error_code == "ACCESS_DENIED"


@pytest.mark.asyncio
async def test_sensitive_tool_does_not_log_response(
    caplog: pytest.LogCaptureFixture,
) -> None:
    secret_value = "SECRET-BANK-ACCOUNT-123"

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["odoo_user_id"] == "42"
        return httpx.Response(
            200,
            content=envelope(data={"account_number": secret_value}),
        )

    with caplog.at_level(logging.INFO, logger="app.tools.executor"):
        result = await run_with_handler(
            handler,
            "profile_get_bank_accounts",
            {},
        )

    assert result.success is True
    assert secret_value not in caplog.text
    assert "profile_get_bank_accounts" in caplog.text


@pytest.mark.asyncio
async def test_unregistered_tool_is_not_executed() -> None:
    called = False

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(200)

    result = await run_with_handler(handler, "unknown_tool", {})

    assert result.error_code == "TOOL_NOT_FOUND"
    assert called is False
