from typing import Annotated, cast

from fastapi import APIRouter, Depends, Request

from app.api.schemas.conversation import ConversationStateResponse
from app.api.security import IngressUserDependency
from app.context.conversation_service import ConversationService
from app.context.pending_action_service import PendingActionService

router = APIRouter(prefix="/conversations", tags=["Conversations"])


def get_conversation_service(request: Request) -> ConversationService:
    return cast(
        ConversationService, request.app.state.conversation_service
    )


def get_pending_action_service(request: Request) -> PendingActionService:
    return cast(
        PendingActionService, request.app.state.pending_action_service
    )


ConversationServiceDependency = Annotated[
    ConversationService, Depends(get_conversation_service)
]
PendingActionServiceDependency = Annotated[
    PendingActionService, Depends(get_pending_action_service)
]


@router.get("/{conversation_id}", response_model=ConversationStateResponse)
async def get_conversation(
    conversation_id: str,
    ingress_user_id: IngressUserDependency,
    service: ConversationServiceDependency,
) -> ConversationStateResponse:
    item = await service.load_owned(conversation_id, ingress_user_id)
    return ConversationStateResponse(
        conversation_id=item.conversation_id,
        status=item.status,
        pending_tool_name=item.pending_tool_name,
        missing_arguments=item.missing_arguments,
        ambiguous_arguments=item.ambiguous_arguments,
        expires_at=item.expires_at,
        data={},
    )


@router.post(
    "/{conversation_id}/reset", response_model=ConversationStateResponse
)
async def reset_conversation(
    conversation_id: str,
    ingress_user_id: IngressUserDependency,
    conversations: ConversationServiceDependency,
    actions: PendingActionServiceDependency,
) -> ConversationStateResponse:
    await actions.cancel_for_conversation(
        conversation_id, odoo_user_id=ingress_user_id
    )
    await conversations.reset(conversation_id, ingress_user_id)
    item = await conversations.load_owned(conversation_id, ingress_user_id)
    return ConversationStateResponse(
        conversation_id=item.conversation_id,
        status=item.status,
        pending_tool_name=item.pending_tool_name,
        missing_arguments=item.missing_arguments,
        ambiguous_arguments=item.ambiguous_arguments,
        expires_at=item.expires_at,
        data={"reset": True},
    )
