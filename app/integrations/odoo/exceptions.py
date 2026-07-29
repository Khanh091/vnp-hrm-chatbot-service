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
            odoo_error_code="ODOO_CONNECTION_ERROR",
        )


class OdooTimeoutError(OdooConnectionError):
    def __init__(self) -> None:
        super().__init__("Odoo request timed out")
        self.odoo_error_code = "ODOO_TIMEOUT"


class OdooContractError(OdooError):
    def __init__(self, message: str = "Odoo returned an invalid response") -> None:
        super().__init__(
            code=ResponseCode.ODOO_CONNECTION_ERROR,
            message=message,
            status_code=HTTPStatus.BAD_GATEWAY,
            odoo_error_code="ODOO_CONTRACT_ERROR",
        )


class OdooBusinessError(OdooError):
    """Compatibility base for callers that catch all Odoo business failures."""

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


class OdooAccessDeniedError(OdooBusinessError):
    def __init__(
        self,
        message: str = "Access denied by Odoo",
        details: dict[str, Any] | None = None,
        odoo_error_code: str = "ACCESS_DENIED",
    ) -> None:
        super().__init__(
            odoo_error_code=odoo_error_code,
            message=message,
            details=details,
            status_code=HTTPStatus.FORBIDDEN,
        )


class OdooRecordNotFoundError(OdooBusinessError):
    def __init__(
        self,
        message: str = "Record not found",
        details: dict[str, Any] | None = None,
        odoo_error_code: str = "RECORD_NOT_FOUND",
    ) -> None:
        super().__init__(
            odoo_error_code=odoo_error_code,
            message=message,
            details=details,
            status_code=HTTPStatus.NOT_FOUND,
        )


class OdooBusinessValidationError(OdooBusinessError):
    pass
