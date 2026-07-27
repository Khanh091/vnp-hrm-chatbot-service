from __future__ import annotations

import logging
from time import perf_counter
from typing import Any

from pydantic import ValidationError

from app.integrations.odoo.client import OdooClient
from app.integrations.odoo.exceptions import OdooError
from app.tools.definitions import (
    ToolExecutionResult,
    ToolResponse,
    TrustedExecutionContext,
)
from app.tools.registry import ToolNotFoundError, ToolRegistry

logger = logging.getLogger(__name__)


class ToolExecutor:
    def __init__(self, registry: ToolRegistry, odoo_client: OdooClient) -> None:
        self._registry = registry
        self._odoo_client = odoo_client

    async def execute(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        *,
        context: TrustedExecutionContext,
        confirmed: bool = False,
    ) -> ToolExecutionResult:
        started = perf_counter()
        status = "failed"
        error_code: str | None = None
        try:
            try:
                tool = self._registry.get(tool_name)
            except ToolNotFoundError:
                error_code = "TOOL_NOT_FOUND"
                return self._failure(
                    tool_name, error_code, "Tool is not registered", started
                )

            if not tool.enabled:
                error_code = "TOOL_DISABLED"
                return self._failure(
                    tool_name, error_code, "Tool is disabled", started
                )

            try:
                validated = tool.argument_schema.model_validate(arguments)
            except ValidationError:
                error_code = "INVALID_ARGUMENTS"
                return self._failure(
                    tool_name,
                    error_code,
                    "Tool arguments failed validation",
                    started,
                )

            if tool.requires_confirmation and not confirmed:
                error_code = "CONFIRMATION_REQUIRED"
                return self._failure(
                    tool_name,
                    error_code,
                    "Explicit confirmation is required",
                    started,
                )

            untrusted_payload = validated.model_dump(mode="json")
            path = self._render_registered_path(
                tool.endpoint,
                tool.path_arguments,
                untrusted_payload,
            )
            payload = {
                key: value
                for key, value in untrusted_payload.items()
                if key not in tool.path_arguments
            }
            # Trusted values are added only after extra fields were rejected.
            payload["odoo_user_id"] = context.odoo_user_id

            response_model = tool.response_schema or ToolResponse
            response = await self._odoo_client.request_registered_tool(
                method=tool.http_method.value,
                path=path,
                request_id=context.request_id,
                response_model=response_model,
                payload=payload,
            )
            status = "success"
            data = response.model_dump(mode="json")
            return ToolExecutionResult(
                tool_name=tool.name,
                success=True,
                data=data,
                latency_ms=self._latency(started),
            )
        except OdooError as error:
            error_code = error.odoo_error_code or error.code.value
            return self._failure(
                tool_name,
                error_code,
                error.message,
                started,
            )
        except (TypeError, ValueError):
            error_code = "TOOL_POLICY_VIOLATION"
            return self._failure(
                tool_name,
                error_code,
                "Registered tool metadata could not be executed safely",
                started,
            )
        finally:
            logger.info(
                "tool_execution tool=%s status=%s error_code=%s latency_ms=%.2f",
                tool_name,
                status,
                error_code,
                self._latency(started),
            )

    @staticmethod
    def _render_registered_path(
        endpoint: str,
        path_arguments: tuple[str, ...],
        arguments: dict[str, Any],
    ) -> str:
        path = endpoint
        for name in path_arguments:
            value = arguments[name]
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError("unsafe path argument")
            path = path.replace(f"{{{name}}}", str(value))
        if "{" in path or "}" in path or "://" in path or ".." in path:
            raise ValueError("unsafe registered path")
        if not path.startswith("/api/hrm-chatbot/v1/"):
            raise ValueError("path is outside the registered API namespace")
        return path

    @staticmethod
    def _latency(started: float) -> float:
        return max(0.0, (perf_counter() - started) * 1000)

    @classmethod
    def _failure(
        cls,
        tool_name: str,
        error_code: str,
        error_message: str,
        started: float,
    ) -> ToolExecutionResult:
        return ToolExecutionResult(
            tool_name=tool_name,
            success=False,
            error_code=error_code,
            error_message=error_message,
            latency_ms=cls._latency(started),
        )
