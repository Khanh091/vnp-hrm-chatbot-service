from http import HTTPStatus
from typing import Any

from app.common.enums import ResponseCode


class AppError(Exception):
    def __init__(
        self,
        *,
        code: ResponseCode,
        message: str,
        status_code: int = HTTPStatus.INTERNAL_SERVER_ERROR,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details or {}
