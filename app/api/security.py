from secrets import compare_digest
from typing import Annotated

from fastapi import Depends, Header, Request

from app.common.enums import ResponseCode
from app.common.exceptions import AppError
from app.config import Settings


async def require_ingress_identity(
    request: Request,
    ingress_key: Annotated[
        str | None, Header(alias="X-HRM-Chatbot-Ingress-Key")
    ] = None,
    odoo_user_id: Annotated[
        int | None, Header(alias="X-Odoo-User-Id")
    ] = None,
) -> int:
    settings: Settings = request.app.state.settings
    expected = settings.chatbot_ingress_api_key.get_secret_value()
    if (
        ingress_key is None
        or not compare_digest(ingress_key.encode(), expected.encode())
    ):
        raise AppError(
            code=ResponseCode.AUTHENTICATION_ERROR,
            message="Ingress authentication failed",
            status_code=401,
        )
    if odoo_user_id is None or odoo_user_id <= 0:
        raise AppError(
            code=ResponseCode.INVALID_REQUEST,
            message="Trusted Odoo identity is required",
            status_code=400,
        )
    return odoo_user_id


IngressUserDependency = Annotated[int, Depends(require_ingress_identity)]
