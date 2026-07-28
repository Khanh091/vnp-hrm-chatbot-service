from typing import Annotated, Protocol, cast
from uuid import uuid4

from fastapi import APIRouter, Depends, Request

from app.api.schemas.chat import ChatRequest, ChatResponse
from app.api.schemas.common import ResponseMeta
from app.api.security import IngressUserDependency
from app.dependencies import OdooClientDependency, RequestIdDependency
from app.orchestration.state import ChatPipelineResult
from app.tools.definitions import TrustedExecutionContext

router = APIRouter(
    prefix="/chat",
    tags=["Chat"],
)


class ChatWorkflow(Protocol):
    async def process(
        self,
        message: str | None,
        trusted_context: TrustedExecutionContext,
        *,
        action_type: str | None = None,
        action_id: str | None = None,
    ) -> ChatPipelineResult: ...


def get_chat_pipeline(request: Request) -> ChatWorkflow:
    return cast(ChatWorkflow, request.app.state.chat_pipeline)


ChatPipelineDependency = Annotated[ChatWorkflow, Depends(get_chat_pipeline)]


@router.post("", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    ingress_user_id: IngressUserDependency,
    odoo_client: OdooClientDependency,
    request_id: RequestIdDependency,
    pipeline: ChatPipelineDependency,
) -> ChatResponse:
    odoo_context = await odoo_client.get_current_user_context(
        odoo_user_id=ingress_user_id,
        request_id=request_id,
    )
    conversation_id = request.conversation_id or str(uuid4())
    trusted_context = TrustedExecutionContext(
            odoo_user_id=odoo_context.user_id,
            employee_id=odoo_context.employee_id,
            company_id=odoo_context.company_id,
            timezone=odoo_context.timezone,
            language=odoo_context.language,
            conversation_id=conversation_id,
            request_id=request_id,
        )
    if request.action is None:
        result = await pipeline.process(request.message, trusted_context)
    else:
        result = await pipeline.process(
            None,
            trusted_context,
            action_type=request.action.type.value,
            action_id=request.action.action_id,
        )
    return ChatResponse(
        conversation_id=result.conversation_id,
        type=result.type,
        answer=result.answer,
        data=result.data,
        timings=result.timings,
        meta=ResponseMeta(request_id=request_id),
    )
