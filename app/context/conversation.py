import asyncio
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict

from app.routing.schemas import ConversationContext


class PendingActionStatus(str, Enum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"
    EXPIRED = "expired"
    EXECUTED = "executed"
    FAILED = "failed"


class ClarificationRequiredData(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    pending_tool: str
    missing_arguments: list[str]
    collected_arguments: dict[str, Any]
    question: str


class ConfirmationRequiredData(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    action_id: str
    tool_name: str
    title: str
    summary: dict[str, Any]
    expires_at: datetime


class PendingAction(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    action_id: str
    conversation_id: str
    user_id: int
    tool_name: str
    validated_arguments: dict[str, Any]
    status: PendingActionStatus
    created_at: datetime
    expires_at: datetime


class ConversationStore:
    """Small process-local state store for the pre-LangGraph phase."""

    def __init__(self, pending_action_ttl_seconds: int) -> None:
        self._ttl = pending_action_ttl_seconds
        self._contexts: dict[str, ConversationContext] = {}
        self._actions: dict[str, PendingAction] = {}
        self._lock = asyncio.Lock()

    async def get_context(
        self, conversation_id: str
    ) -> ConversationContext | None:
        async with self._lock:
            return self._contexts.get(conversation_id)

    async def save_clarification(
        self,
        *,
        conversation_id: str,
        pending_tool: str,
        collected_arguments: dict[str, Any],
        last_user_message: str,
    ) -> None:
        context = ConversationContext(
            conversation_id=conversation_id,
            pending_tool=pending_tool,
            collected_arguments=collected_arguments,
            last_user_message=last_user_message,
        )
        async with self._lock:
            self._contexts[conversation_id] = context

    async def clear_context(self, conversation_id: str) -> None:
        async with self._lock:
            self._contexts.pop(conversation_id, None)

    async def create_pending_action(
        self,
        *,
        conversation_id: str,
        user_id: int,
        tool_name: str,
        validated_arguments: dict[str, Any],
    ) -> PendingAction:
        now = datetime.now(timezone.utc)
        action = PendingAction(
            action_id=f"act-{uuid4()}",
            conversation_id=conversation_id,
            user_id=user_id,
            tool_name=tool_name,
            validated_arguments=validated_arguments,
            status=PendingActionStatus.PENDING,
            created_at=now,
            expires_at=now + timedelta(seconds=self._ttl),
        )
        async with self._lock:
            self._actions[action.action_id] = action
        return action

    async def get_pending_action(
        self,
        action_id: str,
        *,
        user_id: int,
        conversation_id: str,
    ) -> PendingAction | None:
        async with self._lock:
            action = self._actions.get(action_id)
            if action is None:
                return None
            if action.user_id != user_id or action.conversation_id != conversation_id:
                return None
            if (
                action.status is PendingActionStatus.PENDING
                and action.expires_at <= datetime.now(timezone.utc)
            ):
                expired = action.model_copy(
                    update={"status": PendingActionStatus.EXPIRED}
                )
                self._actions[action_id] = expired
                return expired
            return action
