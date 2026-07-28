from __future__ import annotations

from datetime import datetime, timedelta, timezone
from secrets import token_urlsafe
from typing import Any
from uuid import uuid4

from app.context.conversation import PendingActionStatus
from app.persistence.database import Database
from app.persistence.models.pending_action import PendingAction
from app.persistence.repositories import PendingActionRepository


class PendingActionError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class PendingActionService:
    def __init__(
        self, database: Database, ttl_seconds: int, execution_lease_seconds: int
    ) -> None:
        self._database = database
        self._ttl = ttl_seconds
        self._execution_lease = execution_lease_seconds
        self._repository = PendingActionRepository()

    async def create(
        self,
        *,
        conversation_id: str,
        odoo_user_id: int,
        tool_name: str,
        tool_version: str,
        validated_arguments: dict[str, Any],
        display_summary: dict[str, Any],
    ) -> PendingAction:
        now = datetime.now(timezone.utc)
        arguments = dict(validated_arguments)
        idempotency_key = str(
            arguments.pop(
                "idempotency_key", f"chat-{token_urlsafe(24)}"
            )
        )
        async with self._database.session() as session:
            return await self._repository.create(
                session,
                action_id=f"act-{uuid4()}",
                conversation_id=conversation_id,
                odoo_user_id=odoo_user_id,
                tool_name=tool_name,
                tool_version=tool_version,
                validated_arguments=arguments,
                display_summary=display_summary,
                idempotency_key=idempotency_key,
                status=PendingActionStatus.PENDING.value,
                expires_at=now + timedelta(seconds=self._ttl),
            )

    async def load_owned(
        self,
        action_id: str,
        *,
        conversation_id: str,
        odoo_user_id: int,
    ) -> PendingAction:
        now = datetime.now(timezone.utc)
        expired = False
        async with self._database.session() as session:
            item = await self._repository.get(session, action_id)
            self._assert_access(item, conversation_id, odoo_user_id)
            assert item is not None
            if (
                item.status == PendingActionStatus.PENDING.value
                and item.expires_at <= now
            ):
                await self._repository.transition(
                    session,
                    action_id=action_id,
                    odoo_user_id=odoo_user_id,
                    from_statuses=(PendingActionStatus.PENDING.value,),
                    to_status=PendingActionStatus.EXPIRED.value,
                    values={},
                )
                expired = True
            else:
                return item
        if expired:
            raise PendingActionError("ACTION_EXPIRED")
        raise PendingActionError("ACTION_NOT_FOUND")

    async def claim_execution(
        self,
        action_id: str,
        *,
        conversation_id: str,
        odoo_user_id: int,
    ) -> PendingAction:
        now = datetime.now(timezone.utc)
        expired = False
        async with self._database.session() as session:
            current = await self._repository.get(session, action_id)
            self._assert_access(current, conversation_id, odoo_user_id)
            assert current is not None
            if (
                current.status
                in {
                    PendingActionStatus.PENDING.value,
                    PendingActionStatus.CONFIRMED.value,
                }
                and current.expires_at <= now
            ):
                if current.status == PendingActionStatus.PENDING.value:
                    await self._repository.transition(
                        session,
                        action_id=action_id,
                        odoo_user_id=odoo_user_id,
                        from_statuses=(PendingActionStatus.PENDING.value,),
                        to_status=PendingActionStatus.EXPIRED.value,
                        values={},
                    )
                expired = True
            elif current.status == PendingActionStatus.EXECUTING.value:
                lease_expired = (
                    current.executing_at is not None
                    and current.executing_at
                    <= now - timedelta(seconds=self._execution_lease)
                )
                if not lease_expired:
                    raise PendingActionError("ACTION_EXECUTION_IN_PROGRESS")
                reclaimed = await self._repository.transition(
                    session,
                    action_id=action_id,
                    odoo_user_id=odoo_user_id,
                    from_statuses=(PendingActionStatus.EXECUTING.value,),
                    to_status=PendingActionStatus.EXECUTING.value,
                    values={"executing_at": now},
                )
                if reclaimed is None:
                    raise PendingActionError("ACTION_EXECUTION_IN_PROGRESS")
                return reclaimed
            if expired:
                confirmed = None
            else:
                self._raise_terminal_status(current.status)
                confirmed = await self._repository.transition(
                session,
                action_id=action_id,
                odoo_user_id=odoo_user_id,
                from_statuses=(PendingActionStatus.PENDING.value,),
                to_status=PendingActionStatus.CONFIRMED.value,
                values={"confirmed_at": now},
            )
            if not expired and confirmed is None:
                raise PendingActionError("ACTION_EXECUTION_IN_PROGRESS")
            executing = (
                None
                if expired
                else await self._repository.transition(
                session,
                action_id=action_id,
                odoo_user_id=odoo_user_id,
                from_statuses=(PendingActionStatus.CONFIRMED.value,),
                to_status=PendingActionStatus.EXECUTING.value,
                values={"executing_at": now},
                )
            )
            if not expired and executing is None:
                raise PendingActionError("ACTION_EXECUTION_IN_PROGRESS")
            if executing is not None:
                return executing
        raise PendingActionError("ACTION_EXPIRED")

    async def cancel(
        self,
        action_id: str,
        *,
        conversation_id: str,
        odoo_user_id: int,
    ) -> PendingAction:
        await self.load_owned(
            action_id,
            conversation_id=conversation_id,
            odoo_user_id=odoo_user_id,
        )
        async with self._database.session() as session:
            item = await self._repository.transition(
                session,
                action_id=action_id,
                odoo_user_id=odoo_user_id,
                from_statuses=(PendingActionStatus.PENDING.value,),
                to_status=PendingActionStatus.CANCELLED.value,
                values={"cancelled_at": datetime.now(timezone.utc)},
            )
            if item is None:
                raise PendingActionError("ACTION_NOT_CANCELLABLE")
            return item

    async def finish(
        self,
        action_id: str,
        *,
        odoo_user_id: int,
        success: bool,
        error_code: str | None,
        result_summary: dict[str, Any] | None,
    ) -> None:
        now = datetime.now(timezone.utc)
        target = (
            PendingActionStatus.EXECUTED
            if success
            else PendingActionStatus.FAILED
        )
        values: dict[str, Any] = {
            "error_code": error_code,
            "result_summary": result_summary,
            "executed_at" if success else "failed_at": now,
        }
        async with self._database.session() as session:
            item = await self._repository.transition(
                session,
                action_id=action_id,
                odoo_user_id=odoo_user_id,
                from_statuses=(PendingActionStatus.EXECUTING.value,),
                to_status=target.value,
                values=values,
            )
            if item is None:
                raise PendingActionError("WORKFLOW_STATE_CONFLICT")

    async def cancel_for_conversation(
        self, conversation_id: str, *, odoo_user_id: int
    ) -> None:
        now = datetime.now(timezone.utc)
        async with self._database.session() as session:
            item = await self._repository.get_active_for_conversation(
                session,
                conversation_id=conversation_id,
                odoo_user_id=odoo_user_id,
            )
            if item is None:
                return
            if item.status == PendingActionStatus.EXECUTING.value:
                raise PendingActionError("ACTION_EXECUTION_IN_PROGRESS")
            cancelled = await self._repository.transition(
                session,
                action_id=item.action_id,
                odoo_user_id=odoo_user_id,
                from_statuses=(
                    PendingActionStatus.PENDING.value,
                    PendingActionStatus.CONFIRMED.value,
                ),
                to_status=PendingActionStatus.CANCELLED.value,
                values={"cancelled_at": now},
            )
            if cancelled is None:
                raise PendingActionError("WORKFLOW_STATE_CONFLICT")

    @staticmethod
    def _assert_access(
        item: PendingAction | None,
        conversation_id: str,
        odoo_user_id: int,
    ) -> None:
        if item is None:
            raise PendingActionError("ACTION_NOT_FOUND")
        if (
            item.odoo_user_id != odoo_user_id
            or item.conversation_id != conversation_id
        ):
            raise PendingActionError("ACTION_ACCESS_DENIED")

    @staticmethod
    def _raise_terminal_status(status: str) -> None:
        errors = {
            PendingActionStatus.CONFIRMED.value: "ACTION_ALREADY_CONFIRMED",
            PendingActionStatus.EXECUTING.value: "ACTION_EXECUTION_IN_PROGRESS",
            PendingActionStatus.EXECUTED.value: "ACTION_ALREADY_EXECUTED",
            PendingActionStatus.CANCELLED.value: "ACTION_ALREADY_CANCELLED",
            PendingActionStatus.EXPIRED.value: "ACTION_EXPIRED",
            PendingActionStatus.FAILED.value: "ACTION_NOT_CONFIRMABLE",
        }
        if status in errors:
            raise PendingActionError(errors[status])
