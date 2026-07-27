from uuid import uuid4

from fastapi import APIRouter

from app.api.schemas.chat import (
    ChatAcceptedData,
    ChatRequest,
    ChatResponse,
    ValidatedUserContext,
)
from app.api.schemas.common import success_response
from app.dependencies import OdooClientDependency, RequestIdDependency

router = APIRouter(
    prefix="/chat",
    tags=["Chat"],
)


@router.post("", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    odoo_client: OdooClientDependency,
    request_id: RequestIdDependency,
) -> ChatResponse:
    odoo_context = await odoo_client.get_current_user_context(
        odoo_user_id=request.user_context.odoo_user_id,
        request_id=request_id,
    )
    conversation_id = request.conversation_id or str(uuid4())

    return success_response(
        data=ChatAcceptedData(
            conversation_id=conversation_id,
            answer="Chatbot service đã nhận câu hỏi.",
            user_context=ValidatedUserContext.model_validate(
                odoo_context.model_dump(),
            ),
        ),
        request_id=request_id,
        message="Question received",
    )
