from http import HTTPStatus
from typing import Any, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from app.config import Settings
from app.integrations.odoo.exceptions import (
    OdooAuthenticationError,
    OdooBusinessError,
    OdooConnectionError,
)
from app.integrations.odoo.schemas import (
    CurrentUserContextRequest,
    OdooEnvelope,
    OdooHealthData,
    OdooUserContext,
)

ResponseT = TypeVar("ResponseT", bound=BaseModel)


class OdooClient:
    HEALTH_PATH = "/api/hrm-chatbot/v1/health"
    CURRENT_CONTEXT_PATH = "/api/hrm-chatbot/v1/context/current"

    def __init__(
        self,
        settings: Settings,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        timeout = httpx.Timeout(
            connect=settings.odoo_connect_timeout_seconds,
            read=settings.odoo_read_timeout_seconds,
            write=settings.odoo_read_timeout_seconds,
            pool=settings.odoo_connect_timeout_seconds,
        )
        limits = httpx.Limits(
            max_connections=100,
            max_keepalive_connections=20,
            keepalive_expiry=30,
        )
        self._client = httpx.AsyncClient(
            base_url=str(settings.odoo_base_url).rstrip("/"),
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "X-HRM-Chatbot-Key": (
                    settings.odoo_internal_api_key.get_secret_value()
                ),
                "X-Odoo-Database": settings.odoo_database,
            },
            timeout=timeout,
            limits=limits,
            transport=transport,
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def health(self, request_id: str) -> OdooHealthData:
        return await self._request(
            "GET",
            self.HEALTH_PATH,
            request_id=request_id,
            response_model=OdooHealthData,
        )

    async def get_current_user_context(
        self,
        *,
        odoo_user_id: int,
        request_id: str,
    ) -> OdooUserContext:
        payload = CurrentUserContextRequest(odoo_user_id=odoo_user_id)
        return await self._request(
            "POST",
            self.CURRENT_CONTEXT_PATH,
            request_id=request_id,
            response_model=OdooUserContext,
            json=payload.model_dump(),
        )

    async def request_registered_tool(
        self,
        *,
        method: str,
        path: str,
        request_id: str,
        response_model: type[ResponseT],
        payload: dict[str, Any],
    ) -> ResponseT:
        """Transport hook for a path already approved by ToolExecutor."""

        if method == "GET":
            return await self._request(
                method,
                path,
                request_id=request_id,
                response_model=response_model,
                params=payload,
            )
        return await self._request(
            method,
            path,
            request_id=request_id,
            response_model=response_model,
            json=payload,
        )

    async def _request(
        self,
        method: str,
        path: str,
        *,
        request_id: str,
        response_model: type[ResponseT],
        json: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> ResponseT:
        try:
            response = await self._client.request(
                method,
                path,
                headers={"X-Request-ID": request_id},
                json=json,
                params=params,
            )
        except httpx.TimeoutException as error:
            raise OdooConnectionError("Odoo request timed out") from error
        except httpx.RequestError as error:
            raise OdooConnectionError() from error

        try:
            envelope = OdooEnvelope.model_validate(response.json())
        except (ValueError, ValidationError) as error:
            raise OdooConnectionError(
                "Odoo returned an invalid response",
            ) from error

        if not envelope.success:
            self._raise_envelope_error(envelope, response.status_code)

        if response.is_error:
            raise OdooConnectionError(
                f"Odoo returned HTTP {response.status_code}",
            )

        try:
            return response_model.model_validate(envelope.data)
        except ValidationError as error:
            raise OdooConnectionError(
                "Odoo returned invalid response data",
            ) from error

    @staticmethod
    def _raise_envelope_error(
        envelope: OdooEnvelope,
        status_code: int,
    ) -> None:
        if envelope.code == "UNAUTHORIZED" or status_code == HTTPStatus.UNAUTHORIZED:
            raise OdooAuthenticationError(envelope.code)

        client_status = (
            status_code
            if HTTPStatus.BAD_REQUEST <= status_code < HTTPStatus.INTERNAL_SERVER_ERROR
            else HTTPStatus.BAD_GATEWAY
        )
        raise OdooBusinessError(
            odoo_error_code=envelope.code,
            message=envelope.message,
            details=envelope.details,
            status_code=client_status,
        )
