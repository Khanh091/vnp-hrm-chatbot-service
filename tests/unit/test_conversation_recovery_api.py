from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.api.routers.conversations import get_conversation


class FakeConversationService:
    def __init__(self) -> None:
        self.item = SimpleNamespace(
            conversation_id="conv-recovery",
            status="awaiting_confirmation",
            pending_tool_name="leave_create_request",
            missing_arguments=[],
            ambiguous_arguments=[],
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            workflow_data={},
        )

    async def load_owned(self, conversation_id: str, user_id: int):
        assert conversation_id == "conv-recovery"
        assert user_id == 42
        return self.item

    async def recent_messages(
        self,
        conversation_id: str,
        *,
        odoo_user_id: int,
    ):
        assert conversation_id == "conv-recovery"
        assert odoo_user_id == 42
        return [
            {
                "id": 1,
                "role": "assistant",
                "type": "confirmation",
                "text": "Bạn có xác nhận không?",
                "data": {
                    "action_id": (
                        "act-12345678-1234-1234-1234-123456789012"
                    ),
                    "summary": {"reason": "Việc cá nhân"},
                },
                "timestamp": datetime.now(timezone.utc),
            }
        ]


class FakePendingActionService:
    async def get_active_for_conversation(
        self,
        conversation_id: str,
        *,
        odoo_user_id: int,
    ):
        assert conversation_id == "conv-recovery"
        assert odoo_user_id == 42
        return SimpleNamespace(
            action_id="act-12345678-1234-1234-1234-123456789012",
            display_summary={"reason": "Việc cá nhân"},
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=10),
            status="pending",
        )


@pytest.mark.asyncio
async def test_recovery_returns_messages_and_public_pending_confirmation():
    response = await get_conversation(
        "conv-recovery",
        42,
        FakeConversationService(),  # type: ignore[arg-type]
        FakePendingActionService(),  # type: ignore[arg-type]
    )

    assert len(response.messages) == 1
    assert response.pending_confirmation is not None
    assert response.pending_confirmation["action_id"].startswith("act-")
    assert "validated_arguments" not in response.pending_confirmation
    assert "idempotency_key" not in response.pending_confirmation
