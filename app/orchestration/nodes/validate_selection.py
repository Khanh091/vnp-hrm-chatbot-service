from time import perf_counter

from langgraph.runtime import Runtime

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
        update.update(
            {
                "response_type": ChatResponseType.ERROR,
                "response_text": "Yêu cầu không vượt qua kiểm tra an toàn.",
                "response_data": {
                    "issues": [
                        issue.model_dump(mode="json")
                        for issue in result.errors
                    ]
                },
            }
        )
    return update
