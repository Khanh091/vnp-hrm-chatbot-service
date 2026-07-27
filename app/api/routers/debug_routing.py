from typing import Annotated, cast

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field

from app.routing.schemas import RoutingDebugResult
from app.routing.service import RoutingService

router = APIRouter(prefix="/debug/routing", tags=["Debug"])


class DebugRoutingRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str = Field(min_length=1, max_length=4000)


def get_routing_service(request: Request) -> RoutingService:
    return cast(RoutingService, request.app.state.routing_service)


RoutingServiceDependency = Annotated[
    RoutingService,
    Depends(get_routing_service),
]


@router.post("", response_model=RoutingDebugResult)
async def debug_routing(
    request: DebugRoutingRequest,
    service: RoutingServiceDependency,
) -> RoutingDebugResult:
    return await service.route(request.message)
