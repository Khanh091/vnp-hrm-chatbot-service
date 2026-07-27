from uuid import uuid4

from fastapi import APIRouter

from app.api.schemas.chat import ChatRequest, ChatResponse

router = APIRouter(
    prefix="/chat",
    tags=["Chat"],
)


@router.post("", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    conversation_id = request.conversation_id or str(uuid4())

    return ChatResponse(
        conversation_id=conversation_id,
        answer="Chatbot service đã hoạt động.",
    )