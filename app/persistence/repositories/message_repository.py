from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.json import json_safe_dict
from app.persistence.models.conversation_message import ConversationMessage


class MessageRepository:
    async def list_recent(
        self,
        session: AsyncSession,
        *,
        conversation_id: str,
        limit: int,
    ) -> list[ConversationMessage]:
        rows = await session.scalars(
            select(ConversationMessage)
            .where(
                ConversationMessage.conversation_id == conversation_id
            )
            .order_by(ConversationMessage.id.desc())
            .limit(limit)
        )
        return list(reversed(rows.all()))

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
                structured_data=json_safe_dict(structured_data),
                request_id=request_id,
            )
        )
