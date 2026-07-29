from time import perf_counter

from langgraph.runtime import Runtime

from app.common.error_messages import public_error_message
from app.context.conversation import ConversationStatus
from app.orchestration.context import GraphContext
from app.orchestration.nodes.common import routing_context_value, stage_update
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
    ValidationIssueCategory,
)


async def validate_selection_node(
    state: ChatGraphState, runtime: Runtime[GraphContext]
) -> dict[str, object]:
    started = perf_counter()
    if not state.get("pending_tool_name"):
        return _terminal_error(
            state,
            started,
            "PENDING_TOOL_NOT_FOUND",
            "Không còn ngữ cảnh tool hợp lệ.",
        )
    workflow_data = state.get("workflow_data", {})
    classification_data = routing_context_value(state, "classification")
    contexts_data = routing_context_value(state, "candidate_contexts") or []
    if not classification_data or not contexts_data:
        return _terminal_error(
            state,
            started,
            "CLARIFICATION_CONTEXT_MISSING",
            "Ngữ cảnh làm rõ không còn hợp lệ.",
        )

    resolution = ArgumentResolution(
        arguments=state.get("collected_arguments", {}),
        missing_arguments=state.get("missing_arguments", []),
        ambiguous_arguments=state.get("ambiguous_arguments", []),
        rejected_trusted_fields=workflow_data.get(
            "rejected_trusted_fields", []
        ),
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
            "response_text": public_error_message("INVALID_ARGUMENT"),
            "response_data": {
                "reason_code": "INVALID_ARGUMENT",
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
            ToolCandidateContext.model_validate(item) for item in contexts_data
        ],
    )
    security = runtime.context.authorization_policy.validate_security(
        resolution.arguments,
        rejected_trusted_fields=resolution.rejected_trusted_fields,
    )
    if not security.valid:
        all_errors = list(result.errors)
        known = {(issue.code, issue.field) for issue in all_errors}
        all_errors.extend(
            issue
            for issue in security.issues
            if (issue.code, issue.field) not in known
        )
        result = result.model_copy(
            update={
                "valid": False,
                "can_execute": False,
                "requires_clarification": False,
                "requires_confirmation": False,
                "errors": all_errors,
                "security": security,
            }
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
        if ValidationIssueCategory.SECURITY in categories:
            public_code = "SECURITY_REJECTED"
            category = ValidationIssueCategory.SECURITY
        elif ValidationIssueCategory.ARGUMENT in categories:
            public_code = "INVALID_ARGUMENT"
            category = ValidationIssueCategory.ARGUMENT
        else:
            public_code = "ROUTING_AMBIGUOUS"
            category = ValidationIssueCategory.ROUTING
        update.update(
            {
                "response_type": ChatResponseType.ERROR,
                "response_text": public_error_message(public_code, category),
                "response_data": {
                    "reason_code": public_code,
                    "issues": [
                        issue.model_dump(mode="json") for issue in result.errors
                    ],
                },
            }
        )
    return update


def _terminal_error(
    state: ChatGraphState,
    started: float,
    reason_code: str,
    message: str,
) -> dict[str, object]:
    return {
        **stage_update(
            state,
            event="selection_validation_failed",
            timing_name="validation_ms",
            started=started,
        ),
        "workflow_status": WorkflowStatus.FAILED,
        "response_type": ChatResponseType.ERROR,
        "response_text": message,
        "response_data": {"reason_code": reason_code},
    }
