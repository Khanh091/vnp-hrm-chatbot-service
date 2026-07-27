import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from time import perf_counter
from typing import cast
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.middleware.base import RequestResponseEndpoint
from starlette.responses import Response

from app.api.routers.chat import router as chat_router
from app.api.routers.health import router as health_router
from app.api.schemas.common import ErrorResponse, ResponseMeta
from app.common.enums import ResponseCode
from app.common.exceptions import AppError
from app.config import Settings, get_settings
from app.integrations.odoo.client import OdooClient
from app.integrations.odoo.exceptions import OdooError

logger = logging.getLogger("app.requests")


def _error_response(
    *,
    request: Request,
    code: ResponseCode,
    message: str,
    status_code: int,
    details: dict[str, object] | None = None,
) -> JSONResponse:
    payload = ErrorResponse(
        success=False,
        code=code,
        message=message,
        data=None,
        details=details or {},
        meta=ResponseMeta(request_id=request.state.request_id),
    )
    return JSONResponse(
        status_code=status_code,
        content=payload.model_dump(mode="json"),
    )


def create_app(
    *,
    settings: Settings | None = None,
    odoo_client: OdooClient | None = None,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        resolved_settings = settings or get_settings()
        application.state.settings = resolved_settings
        application.state.odoo_client = odoo_client or OdooClient(
            resolved_settings,
        )
        try:
            yield
        finally:
            if odoo_client is None:
                await cast(OdooClient, application.state.odoo_client).close()

    app = FastAPI(
        title="VNPT HRM Chatbot Service",
        version="0.1.0",
        debug=False,
        lifespan=lifespan,
    )

    @app.middleware("http")
    async def request_context_middleware(
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        supplied_request_id = request.headers.get("X-Request-ID", "").strip()
        request_id = (
            supplied_request_id
            if supplied_request_id and len(supplied_request_id) <= 128
            else str(uuid4())
        )
        request.state.request_id = request_id
        started_at = perf_counter()
        response: Response
        try:
            response = await call_next(request)
        except Exception:
            logger.exception(
                "Unhandled request error request_id=%s endpoint=%s",
                request_id,
                request.url.path,
            )
            response = _error_response(
                request=request,
                code=ResponseCode.INTERNAL_ERROR,
                message="Internal server error",
                status_code=500,
            )
        response.headers["X-Request-ID"] = request_id
        latency_ms = (perf_counter() - started_at) * 1000
        logger.info(
            "request_id=%s endpoint=%s status=%s latency_ms=%.2f",
            request_id,
            request.url.path,
            response.status_code,
            latency_ms,
        )
        return response

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        request: Request,
        error: RequestValidationError,
    ) -> JSONResponse:
        details: dict[str, object] = {
            "errors": [
                {
                    "location": ".".join(str(part) for part in item["loc"]),
                    "message": item["msg"],
                    "type": item["type"],
                }
                for item in error.errors()
            ],
        }
        return _error_response(
            request=request,
            code=ResponseCode.INVALID_REQUEST,
            message="Request validation failed",
            status_code=422,
            details=details,
        )

    @app.exception_handler(AppError)
    async def app_exception_handler(
        request: Request,
        error: AppError,
    ) -> JSONResponse:
        if isinstance(error, OdooError):
            logger.warning(
                "Odoo request failed request_id=%s endpoint=%s odoo_error_code=%s",
                request.state.request_id,
                request.url.path,
                error.odoo_error_code or "CONNECTION_ERROR",
            )
        return _error_response(
            request=request,
            code=error.code,
            message=error.message,
            status_code=error.status_code,
            details=error.details,
        )

    app.include_router(health_router, prefix="/api/v1")
    app.include_router(chat_router, prefix="/api/v1")

    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    development_settings = get_settings()
    uvicorn.run(
        "app.main:app",
        host=development_settings.app_host,
        port=development_settings.app_port,
        reload=development_settings.app_debug,
    )
