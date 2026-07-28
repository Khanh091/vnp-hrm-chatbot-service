from typing import Annotated, cast
from uuid import uuid4

from fastapi import APIRouter, Depends, Request

from app.api.schemas.chat import ChatRequest, ChatResponse
from app.api.schemas.common import ResponseMeta
from app.dependencies import OdooClientDependency, RequestIdDependency
from app.orchestration.pipeline import ChatPipeline
from app.tools.definitions import TrustedExecutionContext

router = APIRouter(
    prefix="/chat",
    tags=["Chat"],
)


def get_chat_pipeline(request: Request) -> ChatPipeline:
    return cast(ChatPipeline, request.app.state.chat_pipeline)


ChatPipelineDependency = Annotated[ChatPipeline, Depends(get_chat_pipeline)]


@router.post("", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    odoo_client: OdooClientDependency,
    request_id: RequestIdDependency,
    pipeline: ChatPipelineDependency,
) -> ChatResponse:
    # TODO: require a separate authenticated Odoo-proxy ingress key before
    # exposing this endpoint outside the trusted internal network.
    odoo_context = await odoo_client.get_current_user_context(
        odoo_user_id=request.user_context.odoo_user_id,
        request_id=request_id,
    )
    conversation_id = request.conversation_id or str(uuid4())
    result = await pipeline.process(
        request.message,
        TrustedExecutionContext(
            odoo_user_id=odoo_context.user_id,
            employee_id=odoo_context.employee_id,
            company_id=odoo_context.company_id,
            timezone=odoo_context.timezone,
            language=odoo_context.language,
            conversation_id=conversation_id,
            request_id=request_id,
        ),
    )
    return ChatResponse(
        conversation_id=result.conversation_id,
        type=result.type,
        answer=result.answer,
        data=result.data,
        timings=result.timings,
        meta=ResponseMeta(request_id=request_id),
    )
