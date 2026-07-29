from time import perf_counter

from langgraph.runtime import Runtime

from app.context.conversation import ConversationStatus
from app.orchestration.context import GraphContext
from app.orchestration.nodes.common import stage_update
from app.orchestration.state import (
    ChatGraphState,
    ChatResponseType,
    WorkflowStatus,
)
from app.routing.argument_resolver import ArgumentResolution
from app.routing.schemas import (
    QueryClassification,
    ToolCandidateContext,
    ToolSelection,
)


async def validate_selection_node(
    state: ChatGraphState, runtime: Runtime[GraphContext]
) -> dict[str, object]:
    started = perf_counter()
    if not state.get("pending_tool_name"):
        return {
            **stage_update(
                state,
                event="selection_validation_failed",
                timing_name="validation_ms",
                started=started,
            ),
            "workflow_status": WorkflowStatus.FAILED,
            "response_type": ChatResponseType.ERROR,
            "response_text": "Không còn ngữ cảnh tool hợp lệ.",
            "response_data": {"reason_code": "PENDING_TOOL_NOT_FOUND"},
        }
    workflow_data = state.get("workflow_data", {})
    classification_data = state.get("classification") or workflow_data.get(
        "classification"
    )
    contexts_data = state.get("candidate_contexts") or workflow_data.get(
        "candidate_contexts", []
    )
    if not classification_data or not contexts_data:
        return {
            **stage_update(
                state,
                event="selection_validation_failed",
                timing_name="validation_ms",
                started=started,
            ),
            "workflow_status": WorkflowStatus.FAILED,
            "response_type": ChatResponseType.ERROR,
            "response_text": "Ngữ cảnh làm rõ không còn hợp lệ.",
            "response_data": {"reason_code": "CLARIFICATION_CONTEXT_MISSING"},
        }
    resolution = ArgumentResolution(
        arguments=state.get("collected_arguments", {}),
        missing_arguments=state.get("missing_arguments", []),
        ambiguous_arguments=state.get("ambiguous_arguments", []),
    )
    slot_issues = workflow_data.get("slot_issues", [])
    if slot_issues:
        await runtime.context.conversation_service.clear_workflow(
            state["conversation_id"],
            int(state["trusted_context"]["odoo_user_id"]),
            status=ConversationStatus.FAILED,
        )
        return {
            **stage_update(
                state,
                event="slot_validation_failed",
                timing_name="validation_ms",
                started=started,
            ),
            "workflow_status": WorkflowStatus.FAILED,
            "response_type": ChatResponseType.ERROR,
            "response_text": "Khoảng ngày hoặc thông tin đã nhập chưa hợp lệ.",
            "response_data": {
                "reason_code": "INVALID_ARGUMENTS",
                "issues": slot_issues,
            },
            "pending_tool_name": None,
            "collected_arguments": {},
            "missing_arguments": [],
            "ambiguous_arguments": [],
            "workflow_data": {},
        }
    result = runtime.context.validator.validate(
        ToolSelection.model_validate(state["selection"]),
        resolution,
        classification=QueryClassification.model_validate(
            classification_data
        ),
        candidates=[
            ToolCandidateContext.model_validate(item)
            for item in contexts_data
        ],
    )
    if result.requires_clarification:
        status = WorkflowStatus.CLARIFICATION_REQUIRED
    elif result.requires_confirmation:
        status = WorkflowStatus.CONFIRMATION_REQUIRED
    elif result.can_execute:
        status = WorkflowStatus.EXECUTE_READ
    else:
        status = WorkflowStatus.FAILED
    update = stage_update(
        state,
        event="selection_validated",
        timing_name="validation_ms",
        started=started,
        data={"status": status.value},
    )
    update.update(
        {
            "validation": result.model_dump(mode="json"),
            "workflow_status": status,
            "collected_arguments": result.normalized_arguments,
        }
    )
    if status is WorkflowStatus.FAILED:
        await runtime.context.conversation_service.clear_workflow(
            state["conversation_id"],
            int(state["trusted_context"]["odoo_user_id"]),
            status=ConversationStatus.FAILED,
        )
        categories = {issue.category for issue in result.errors}
        if "security" in categories:
            response_text = "Bạn không có quyền thực hiện yêu cầu này."
            public_code = "ACCESS_DENIED"
        elif "arguments" in categories:
            response_text = "Thông tin đầu vào chưa hợp lệ."
            public_code = "INVALID_ARGUMENTS"
        else:
            response_text = "Tôi chưa xác định chính xác thông tin bạn muốn tra cứu."
            public_code = "ROUTING_AMBIGUOUS"
        update.update(
            {
                "response_type": ChatResponseType.ERROR,
                "response_text": response_text,
                "response_data": {
                    "reason_code": public_code,
                    "issues": [
                        issue.model_dump(mode="json")
                        for issue in result.errors
                    ]
                },
            }
        )
    return update
