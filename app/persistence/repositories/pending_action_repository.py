from datetime import datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.persistence.models.pending_action import PendingAction


class PendingActionRepository:
    async def get(
        self, session: AsyncSession, action_id: str
    ) -> PendingAction | None:
        return await session.scalar(
            select(PendingAction).where(PendingAction.action_id == action_id)
        )

    async def create(
        self,
        session: AsyncSession,
        **values: Any,
    ) -> PendingAction:
        item = PendingAction(**values)
        session.add(item)
        await session.flush()
        return item

    async def transition(
        self,
        session: AsyncSession,
        *,
        action_id: str,
        odoo_user_id: int,
        from_statuses: tuple[str, ...],
        to_status: str,
        values: dict[str, Any],
    ) -> PendingAction | None:
        statement = (
            update(PendingAction)
            .where(
                PendingAction.action_id == action_id,
                PendingAction.odoo_user_id == odoo_user_id,
                PendingAction.status.in_(from_statuses),
            )
            .values(status=to_status, **values)
            .returning(PendingAction)
        )
        result = await session.execute(statement)
        return result.scalar_one_or_none()

    async def expire(
        self, session: AsyncSession, *, now: datetime
    ) -> int:
        result = await session.execute(
            update(PendingAction)
            .where(
                PendingAction.status == "pending",
                PendingAction.expires_at <= now,
            )
            .values(status="expired")
        )
        return int(result.rowcount or 0)
