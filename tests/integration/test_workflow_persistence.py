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
from app.workflows import SlotManager, build_workflow_registry


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


@pytest.mark.asyncio
async def test_slot_filling_resumes_after_database_restart() -> None:
    settings = get_settings()
    conversation_id = f"test-slot-restart-{uuid4()}"
    user_id = 900_000_002
    trusted = TrustedExecutionContext(
        odoo_user_id=user_id,
        employee_id=1,
        company_id=1,
        timezone="Asia/Ho_Chi_Minh",
        conversation_id=conversation_id,
        request_id="test-slot-restart",
    )
    first_database = Database(settings.database_url)
    try:
        first_service = ConversationService(
            first_database,
            settings.conversation_state_ttl_seconds,
        )
        try:
            conversation = await first_service.load_or_create(
                conversation_id,
                trusted,
            )
        except OperationalError:
            pytest.skip("PostgreSQL integration database is unavailable")
        await first_service.update(
            conversation,
            status=ConversationStatus.AWAITING_CLARIFICATION,
            pending_tool_name="leave_create_request",
            collected_arguments={"date_from": "2026-07-29"},
            missing_arguments=["date_to", "leave_type_id"],
            workflow_data={"current_field": "date_to"},
        )
    finally:
        await first_database.close()

    second_database = Database(settings.database_url)
    try:
        second_service = ConversationService(
            second_database,
            settings.conversation_state_ttl_seconds,
        )
        restored = await second_service.load_owned(conversation_id, user_id)
        workflow = build_workflow_registry().get("leave_create_request")
        assert workflow is not None
        manager = SlotManager()
        state = manager.initialize(workflow, restored.collected_arguments)
        state = manager.merge(
            workflow,
            state,
            {"date_to": "2026-07-30"},
        )
        assert state.values["date_from"] == "2026-07-29"
        assert manager.get_next_slot(workflow, state) == "leave_type_id"
        await second_service.clear_workflow(conversation_id, user_id)
        cleared = await second_service.load_owned(conversation_id, user_id)
        assert cleared.pending_tool_name is None
        assert cleared.active_workflow is None
        assert cleared.collected_arguments == {}
        assert cleared.missing_arguments == []
        assert cleared.workflow_data == {}
    finally:
        try:
            async with second_database.session() as session:
                await session.execute(
                    delete(Conversation).where(
                        Conversation.conversation_id == conversation_id
                    )
                )
        except OperationalError:
            pass
        await second_database.close()
