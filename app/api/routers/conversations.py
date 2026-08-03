from datetime import datetime, timezone
from typing import Annotated, cast

from fastapi import APIRouter, Depends, Request

from app.api.schemas.conversation import ConversationStateResponse
from app.api.security import IngressUserDependency
from app.context.conversation import ConversationStatus
from app.context.conversation_service import (
    ConversationService,
    ConversationStateError,
)
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
    actions: PendingActionServiceDependency,
) -> ConversationStateResponse:
    item = await service.load_owned(conversation_id, ingress_user_id)
    if item.expires_at <= datetime.now(timezone.utc):
        raise ConversationStateError("CONVERSATION_EXPIRED")
    messages = await service.recent_messages(
        conversation_id,
        odoo_user_id=ingress_user_id,
    )
    active_action = await actions.get_active_for_conversation(
        conversation_id,
        odoo_user_id=ingress_user_id,
    )
    workflow_data = item.workflow_data or {}
    pending_clarification = None
    if item.status == ConversationStatus.AWAITING_CLARIFICATION.value:
        pending_clarification = workflow_data.get("clarification_metadata")
    pending_confirmation = None
    if (
        item.status == ConversationStatus.AWAITING_CONFIRMATION.value
        and active_action is not None
    ):
        confirmation_title = next(
            (
                message.get("data", {}).get("title")
                for message in reversed(messages)
                if message.get("type") == "confirmation"
                and isinstance(message.get("data"), dict)
                and message.get("data", {}).get("title")
            ),
            "Xác nhận thao tác",
        )
        pending_confirmation = {
            "action_id": active_action.action_id,
            "title": confirmation_title,
            "summary": active_action.display_summary,
            "expires_at": active_action.expires_at,
            "status": active_action.status,
        }
    return ConversationStateResponse(
        conversation_id=item.conversation_id,
        status=item.status,
        pending_tool_name=item.pending_tool_name,
        missing_arguments=item.missing_arguments,
        ambiguous_arguments=item.ambiguous_arguments,
        expires_at=item.expires_at,
        messages=messages,
        pending_clarification=pending_clarification,
        pending_confirmation=pending_confirmation,
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
        messages=[],
        pending_clarification=None,
        pending_confirmation=None,
        data={"reset": True},
    )
