from http import HTTPStatus
from typing import Any

from app.common.enums import ResponseCode
from app.common.exceptions import AppError


class OdooError(AppError):
    def __init__(
        self,
        *,
        code: ResponseCode,
        message: str,
        status_code: int,
        odoo_error_code: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            code=code,
            message=message,
            status_code=status_code,
            details=details,
        )
        self.odoo_error_code = odoo_error_code


class OdooAuthenticationError(OdooError):
    def __init__(self, odoo_error_code: str = "UNAUTHORIZED") -> None:
        super().__init__(
            code=ResponseCode.ODOO_AUTHENTICATION_ERROR,
            message="Odoo authentication failed",
            status_code=HTTPStatus.BAD_GATEWAY,
            odoo_error_code=odoo_error_code,
        )


class OdooConnectionError(OdooError):
    def __init__(self, message: str = "Odoo service is unavailable") -> None:
        super().__init__(
            code=ResponseCode.ODOO_CONNECTION_ERROR,
            message=message,
            status_code=HTTPStatus.SERVICE_UNAVAILABLE,
        )


class OdooBusinessError(OdooError):
    def __init__(
        self,
        *,
        odoo_error_code: str,
        message: str,
        details: dict[str, Any] | None = None,
        status_code: int = HTTPStatus.BAD_REQUEST,
    ) -> None:
        super().__init__(
            code=ResponseCode.ODOO_BUSINESS_ERROR,
            message=message,
            status_code=status_code,
            odoo_error_code=odoo_error_code,
            details=details,
        )
