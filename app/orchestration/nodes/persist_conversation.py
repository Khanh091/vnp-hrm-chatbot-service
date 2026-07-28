from time import perf_counter
from typing import Any

from langgraph.runtime import Runtime

from app.context.conversation import MessageRole, MessageType
from app.orchestration.context import GraphContext
from app.orchestration.nodes.common import stage_update
from app.orchestration.state import ChatGraphState, ChatResponseType


async def persist_conversation_node(
    state: ChatGraphState, runtime: Runtime[GraphContext]
) -> dict[str, object]:
    started = perf_counter()
    message = state.get("user_message")
    if message:
        await runtime.context.conversation_service.add_message(
            conversation_id=state["conversation_id"],
            role=MessageRole.USER,
            message_type=MessageType.TEXT,
            content=message,
            structured_data={},
            request_id=state["request_id"],
        )
    response_type = state.get("response_type")
    message_types = {
        ChatResponseType.CLARIFICATION_REQUIRED: MessageType.CLARIFICATION,
        ChatResponseType.CONFIRMATION_REQUIRED: MessageType.CONFIRMATION,
        ChatResponseType.ERROR: MessageType.ERROR,
    }
    message_type = (
        message_types.get(response_type, MessageType.TEXT)
        if response_type is not None
        else MessageType.TEXT
    )
    response_data = state.get("response_data") or {}
    safe_keys = {
        "error_code",
        "action_id",
        "status",
        "field",
        "options",
        "title",
        "summary",
        "expires_at",
    }
    safe_data: dict[str, Any] = {
        key: response_data[key]
        for key in safe_keys
        if key in response_data
    }
    await runtime.context.conversation_service.add_message(
        conversation_id=state["conversation_id"],
        role=MessageRole.ASSISTANT,
        message_type=message_type,
        content=state.get("response_text"),
        structured_data=safe_data,
        request_id=state["request_id"],
    )
    return stage_update(
        state,
        event="conversation_persisted",
        timing_name="conversation_persist_ms",
        started=started,
    )
