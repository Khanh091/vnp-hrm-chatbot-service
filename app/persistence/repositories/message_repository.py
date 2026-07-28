from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.persistence.models.conversation_message import ConversationMessage


class MessageRepository:
    async def add(
        self,
        session: AsyncSession,
        *,
        conversation_id: str,
        role: str,
        message_type: str,
        content: str | None,
        structured_data: dict[str, Any],
        request_id: str,
    ) -> None:
        session.add(
            ConversationMessage(
                conversation_id=conversation_id,
                role=role,
                message_type=message_type,
                content=content,
                structured_data=structured_data,
                request_id=request_id,
            )
        )
