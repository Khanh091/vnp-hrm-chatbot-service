from datetime import datetime
from typing import Any, cast

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.json import json_safe_dict
from app.persistence.models.pending_action import PendingAction

_CREATE_JSON_FIELDS = {
    "validated_arguments",
    "display_summary",
    "result_summary",
}


class PendingActionRepository:
    async def get(
        self, session: AsyncSession, action_id: str
    ) -> PendingAction | None:
        return cast(
            PendingAction | None,
            await session.scalar(
                select(PendingAction).where(
                    PendingAction.action_id == action_id
                )
            ),
        )

    async def get_active_for_conversation(
        self,
        session: AsyncSession,
        *,
        conversation_id: str,
        odoo_user_id: int,
    ) -> PendingAction | None:
        return cast(
            PendingAction | None,
            await session.scalar(
                select(PendingAction)
                .where(
                    PendingAction.conversation_id == conversation_id,
                    PendingAction.odoo_user_id == odoo_user_id,
                    PendingAction.status.in_(
                        ("pending", "confirmed", "executing")
                    ),
                )
                .order_by(PendingAction.created_at.desc())
                .limit(1)
            ),
        )

    async def create(
        self,
        session: AsyncSession,
        **values: Any,
    ) -> PendingAction:
        persisted_values = dict(values)
        for field in _CREATE_JSON_FIELDS:
            value = persisted_values.get(field)
            if isinstance(value, dict):
                persisted_values[field] = json_safe_dict(value)
        item = PendingAction(**persisted_values)
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
        persisted_values = dict(values)
        result_summary = persisted_values.get("result_summary")
        if isinstance(result_summary, dict):
            persisted_values["result_summary"] = json_safe_dict(
                result_summary
            )
        statement = (
            update(PendingAction)
            .where(
                PendingAction.action_id == action_id,
                PendingAction.odoo_user_id == odoo_user_id,
                PendingAction.status.in_(from_statuses),
            )
            .values(status=to_status, **persisted_values)
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
        return int(getattr(result, "rowcount", 0) or 0)
