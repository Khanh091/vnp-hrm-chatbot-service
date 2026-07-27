import json

import httpx
import pytest

from app.integrations.odoo.client import OdooClient
from app.integrations.odoo.exceptions import (
    OdooBusinessError,
    OdooConnectionError,
)
from tests.conftest import build_settings


def envelope(
    *,
    success: bool,
    code: str,
    data: object = None,
    message: str = "Success",
) -> bytes:
    return json.dumps(
        {
            "success": success,
            "code": code,
            "message": message,
            "data": data,
            "meta": {
                "request_id": "request-1",
                "timestamp": "2026-07-27T00:00:00Z",
            },
        }
    ).encode()


@pytest.mark.asyncio
async def test_odoo_health_success() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["X-Request-ID"] == "request-1"
        assert request.headers["X-HRM-Chatbot-Key"] == "test-key"
        return httpx.Response(
            200,
            content=envelope(
                success=True,
                code="SUCCESS",
                data={"service": "vnpt_hrm_chatbot_api", "version": "1.0"},
            ),
        )

    client = OdooClient(
        build_settings(),
        transport=httpx.MockTransport(handler),
    )
    try:
        result = await client.health("request-1")
    finally:
        await client.close()

    assert result.service == "vnpt_hrm_chatbot_api"
    assert result.version == "1.0"


@pytest.mark.asyncio
async def test_odoo_timeout() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out", request=request)

    client = OdooClient(
        build_settings(),
        transport=httpx.MockTransport(handler),
    )
    try:
        with pytest.raises(OdooConnectionError, match="timed out"):
            await client.health("request-1")
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_odoo_error_envelope() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            404,
            content=envelope(
                success=False,
                code="USER_NOT_FOUND",
                message="User not found",
            ),
        )

    client = OdooClient(
        build_settings(),
        transport=httpx.MockTransport(handler),
    )
    try:
        with pytest.raises(OdooBusinessError) as error:
            await client.health("request-1")
    finally:
        await client.close()

    assert error.value.odoo_error_code == "USER_NOT_FOUND"
