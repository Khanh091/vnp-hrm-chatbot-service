from datetime import datetime, timezone
from typing import Generic, TypeVar

from pydantic import BaseModel, Field

from app.common.enums import ResponseCode

DataT = TypeVar("DataT")


class ResponseMeta(BaseModel):
    request_id: str
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
    )


class ApiResponse(BaseModel, Generic[DataT]):
    success: bool
    code: str
    message: str
    data: DataT | None
    meta: ResponseMeta


def success_response(
    *,
    data: DataT,
    request_id: str,
    message: str,
) -> ApiResponse[DataT]:
    return ApiResponse[DataT](
        success=True,
        code=ResponseCode.SUCCESS,
        message=message,
        data=data,
        meta=ResponseMeta(request_id=request_id),
    )


class ErrorResponse(ApiResponse[None]):
    details: dict[str, object] = Field(default_factory=dict)
