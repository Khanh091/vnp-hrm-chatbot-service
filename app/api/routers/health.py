from fastapi import APIRouter
from pydantic import BaseModel

from app.api.schemas.common import ApiResponse, success_response
from app.dependencies import RequestIdDependency

router = APIRouter(
    prefix="/health",
    tags=["Health"],
)


class HealthData(BaseModel):
    service: str
    version: str


@router.get("", response_model=ApiResponse[HealthData])
async def health_check(request_id: RequestIdDependency) -> ApiResponse[HealthData]:
    return success_response(
        data=HealthData(
            service="vnpt-hrm-chatbot-service",
            version="0.1.0",
        ),
        request_id=request_id,
        message="Chatbot service is available",
    )
