from datetime import datetime
from typing import Any, cast

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.persistence.models.conversation import Conversation


class ConversationRepository:
    async def get(
        self, session: AsyncSession, conversation_id: str
    ) -> Conversation | None:
        return cast(
            Conversation | None,
            await session.scalar(
                select(Conversation).where(
                Conversation.conversation_id == conversation_id
                )
            ),
        )

    async def create(
        self,
        session: AsyncSession,
        *,
        conversation_id: str,
        odoo_user_id: int,
        employee_id: int | None,
        company_id: int | None,
        status: str,
        expires_at: datetime,
    ) -> Conversation:
        item = Conversation(
            conversation_id=conversation_id,
            odoo_user_id=odoo_user_id,
            employee_id=employee_id,
            company_id=company_id,
            status=status,
            expires_at=expires_at,
        )
        session.add(item)
        await session.flush()
        return item

    async def update_state(
        self,
        session: AsyncSession,
        *,
        conversation_id: str,
        expected_version: int,
        values: dict[str, Any],
    ) -> bool:
        result = await session.execute(
            update(Conversation)
            .where(
                Conversation.conversation_id == conversation_id,
                Conversation.version == expected_version,
            )
            .values(**values, version=Conversation.version + 1)
        )
        return bool(getattr(result, "rowcount", 0))
