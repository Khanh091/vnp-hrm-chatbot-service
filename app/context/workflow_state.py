from __future__ import annotations

from typing import Any

from app.persistence.models.conversation import Conversation


def clear_active_workflow(conversation: Conversation) -> dict[str, Any]:
    """Clear all resumable fields and return matching repository values."""
    conversation.active_workflow = None
    conversation.pending_tool_name = None
    conversation.collected_arguments = {}
    conversation.missing_arguments = []
    conversation.ambiguous_arguments = []
    conversation.workflow_data = {}
    return {
        "active_workflow": None,
        "pending_tool_name": None,
        "collected_arguments": {},
        "missing_arguments": [],
        "ambiguous_arguments": [],
        "workflow_data": {},
    }
