from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from app.context.conversation import (
    ConversationStatus,
    MessageRole,
    MessageType,
)
from app.context.workflow_state import clear_active_workflow
from app.persistence.database import Database
from app.persistence.models.conversation import Conversation
from app.persistence.repositories import (
    ConversationRepository,
    MessageRepository,
)
from app.tools.definitions import TrustedExecutionContext


class ConversationStateError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class ConversationService:
    def __init__(self, database: Database, ttl_seconds: int) -> None:
        self._database = database
        self._ttl = ttl_seconds
        self._conversations = ConversationRepository()
        self._messages = MessageRepository()

    async def load_or_create(
        self,
        conversation_id: str,
        trusted_context: TrustedExecutionContext,
    ) -> Conversation:
        now = datetime.now(timezone.utc)
        expired = False
        async with self._database.session() as session:
            item = await self._conversations.get(session, conversation_id)
            if item is None:
                return await self._conversations.create(
                    session,
                    conversation_id=conversation_id,
                    odoo_user_id=trusted_context.odoo_user_id,
                    employee_id=trusted_context.employee_id,
                    company_id=trusted_context.company_id,
                    status=ConversationStatus.ACTIVE.value,
                    expires_at=now + timedelta(seconds=self._ttl),
                )
            self._assert_owner(item, trusted_context.odoo_user_id)
            if item.expires_at <= now and item.status in {
                ConversationStatus.AWAITING_CLARIFICATION.value,
                ConversationStatus.AWAITING_CONFIRMATION.value,
            }:
                item.status = ConversationStatus.EXPIRED.value
                clear_active_workflow(item)
                await session.flush()
                expired = True
            else:
                return item
        if expired:
            raise ConversationStateError("CONVERSATION_EXPIRED")
        raise ConversationStateError("INVALID_CONVERSATION_STATE")

    async def load_owned(
        self, conversation_id: str, odoo_user_id: int
    ) -> Conversation:
        async with self._database.session() as session:
            item = await self._conversations.get(session, conversation_id)
            if item is None:
                raise ConversationStateError("CONVERSATION_NOT_FOUND")
            self._assert_owner(item, odoo_user_id)
            return item

    async def update(
        self,
        conversation: Conversation,
        *,
        status: ConversationStatus,
        pending_tool_name: str | None = None,
        collected_arguments: dict[str, Any] | None = None,
        missing_arguments: list[str] | None = None,
        ambiguous_arguments: list[str] | None = None,
        workflow_data: dict[str, Any] | None = None,
    ) -> None:
        if status not in {
            ConversationStatus.AWAITING_CLARIFICATION,
            ConversationStatus.AWAITING_CONFIRMATION,
        } and (pending_tool_name is not None or missing_arguments):
            raise ConversationStateError("INVALID_CONVERSATION_STATE")
        now = datetime.now(timezone.utc)
        values: dict[str, Any] = {
            "status": status.value,
            "active_workflow": (
                pending_tool_name
                if status is ConversationStatus.AWAITING_CLARIFICATION
                else None
            ),
            "pending_tool_name": pending_tool_name,
            "collected_arguments": collected_arguments or {},
            "missing_arguments": missing_arguments or [],
            "ambiguous_arguments": ambiguous_arguments or [],
            "workflow_data": workflow_data or {},
            "last_message_at": now,
            "expires_at": now + timedelta(seconds=self._ttl),
        }
        async with self._database.session() as session:
            changed = await self._conversations.update_state(
                session,
                conversation_id=conversation.conversation_id,
                expected_version=conversation.version,
                values=values,
            )
            if not changed:
                raise ConversationStateError("WORKFLOW_STATE_CONFLICT")

    async def add_message(
        self,
        *,
        conversation_id: str,
        role: MessageRole,
        message_type: MessageType,
        content: str | None,
        structured_data: dict[str, Any],
        request_id: str,
    ) -> None:
        async with self._database.session() as session:
            await self._messages.add(
                session,
                conversation_id=conversation_id,
                role=role.value,
                message_type=message_type.value,
                content=content,
                structured_data=structured_data,
                request_id=request_id,
            )

    async def recent_messages(
        self,
        conversation_id: str,
        *,
        odoo_user_id: int,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        await self.load_owned(conversation_id, odoo_user_id)
        async with self._database.session() as session:
            items = await self._messages.list_recent(
                session,
                conversation_id=conversation_id,
                limit=min(max(limit, 1), 100),
            )
            return [
                {
                    "id": item.id,
                    "role": item.role,
                    "type": item.message_type,
                    "text": item.content,
                    "data": item.structured_data,
                    "timestamp": item.created_at,
                }
                for item in items
                if item.role in {
                    MessageRole.USER.value,
                    MessageRole.ASSISTANT.value,
                    MessageRole.SYSTEM.value,
                }
            ]

    async def reset(
        self, conversation_id: str, odoo_user_id: int
    ) -> None:
        item = await self.load_owned(conversation_id, odoo_user_id)
        await self.update(item, status=ConversationStatus.CANCELLED)

    async def clear_workflow(
        self,
        conversation_id: str,
        odoo_user_id: int,
        *,
        status: ConversationStatus = ConversationStatus.ACTIVE,
    ) -> None:
        item = await self.load_owned(conversation_id, odoo_user_id)
        await self.update(
            item,
            status=status,
            pending_tool_name=None,
            collected_arguments={},
            missing_arguments=[],
            ambiguous_arguments=[],
            workflow_data={},
        )

    async def clear_active_workflow(
        self,
        conversation_id: str,
        odoo_user_id: int,
        *,
        status: ConversationStatus = ConversationStatus.ACTIVE,
    ) -> None:
        """Clear all resumable workflow fields in one ownership-checked update."""
        await self.clear_workflow(
            conversation_id,
            odoo_user_id,
            status=status,
        )

    @staticmethod
    def _assert_owner(item: Conversation, odoo_user_id: int) -> None:
        if item.odoo_user_id != odoo_user_id:
            raise ConversationStateError("CONVERSATION_ACCESS_DENIED")
