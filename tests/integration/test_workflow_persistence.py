import asyncio
from uuid import uuid4

import pytest
from sqlalchemy import delete
from sqlalchemy.exc import OperationalError

from app.config import get_settings
from app.context.conversation import ConversationStatus
from app.context.conversation_service import ConversationService
from app.context.pending_action_service import (
    PendingActionError,
    PendingActionService,
)
from app.persistence.database import Database
from app.persistence.models import (
    Conversation,
    ConversationMessage,
    PendingAction,
)
from app.tools.definitions import TrustedExecutionContext


@pytest.mark.asyncio
async def test_concurrent_confirmation_claims_execution_once() -> None:
    settings = get_settings()
    database = Database(settings.database_url)
    conversation_id = f"test-concurrent-{uuid4()}"
    user_id = 900_000_001
    conversations = ConversationService(
        database, settings.conversation_state_ttl_seconds
    )
    actions = PendingActionService(
        database,
        settings.pending_action_ttl_seconds,
        settings.pending_execution_lease_seconds,
    )
    trusted = TrustedExecutionContext(
        odoo_user_id=user_id,
        employee_id=1,
        company_id=1,
        timezone="Asia/Ho_Chi_Minh",
        conversation_id=conversation_id,
        request_id="test-concurrent",
    )
    try:
        try:
            conversation = await conversations.load_or_create(
                conversation_id, trusted
            )
        except OperationalError:
            pytest.skip("PostgreSQL integration database is unavailable")
        await conversations.update(
            conversation,
            status=ConversationStatus.AWAITING_CONFIRMATION,
            pending_tool_name="leave_cancel_request",
        )
        action = await actions.create(
            conversation_id=conversation_id,
            odoo_user_id=user_id,
            tool_name="leave_cancel_request",
            tool_version="1.0",
            validated_arguments={
                "request_id": 12,
                "idempotency_key": f"test-{uuid4()}",
            },
            display_summary={"request_id": 12},
        )

        async def claim() -> str:
            try:
                item = await actions.claim_execution(
                    action.action_id,
                    conversation_id=conversation_id,
                    odoo_user_id=user_id,
                )
                return item.status
            except PendingActionError as error:
                return error.code

        results = await asyncio.gather(claim(), claim())
        assert sorted(results) == [
            "ACTION_EXECUTION_IN_PROGRESS",
            "executing",
        ]
    finally:
        try:
            async with database.session() as session:
                await session.execute(
                    delete(PendingAction).where(
                        PendingAction.conversation_id == conversation_id
                    )
                )
                await session.execute(
                    delete(ConversationMessage).where(
                        ConversationMessage.conversation_id == conversation_id
                    )
                )
                await session.execute(
                    delete(Conversation).where(
                        Conversation.conversation_id == conversation_id
                    )
                )
        except OperationalError:
            pass
        await database.close()
