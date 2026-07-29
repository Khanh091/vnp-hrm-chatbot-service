from time import perf_counter

from langgraph.runtime import Runtime

from app.context.conversation import ConversationStatus
from app.context.entities import ResolvedSubject
from app.orchestration.context import GraphContext
from app.orchestration.nodes.common import stage_update
from app.orchestration.state import ChatGraphState
from app.routing.schemas import QueryClassification
from app.security.authorization import AuthorizationDecision, AuthorizationRequest
from app.tools.definitions import (
    ToolExecutionResult,
    TrustedExecutionContext,
    ValidatedToolExecution,
)


async def execute_read_tool_node(
    state: ChatGraphState, runtime: Runtime[GraphContext]
) -> dict[str, object]:
    started = perf_counter()
    tool_name = state["pending_tool_name"]
    assert tool_name is not None
    trusted = TrustedExecutionContext.model_validate(state["trusted_context"])
    classification = QueryClassification.model_validate(
        state["classification"]
    )
    assert classification.intent is not None
    decision = runtime.context.authorization_policy.authorize(
        AuthorizationRequest(
            tool_name=tool_name,
            intent=classification.intent,
            operation=classification.operation,
            scope=classification.scope,
            trusted_context=trusted,
            resolved_subject=(
                ResolvedSubject(
                    scope=classification.scope,
                    employee_id=trusted.employee_id,
                    source="trusted_context",
                )
                if classification.scope.value == "self"
                else None
            ),
        ),
        allowed_tools={
            str(candidate["tool_name"])
            for candidate in state.get("candidate_contexts", [])
        },
    )
    if decision.allowed:
        result = await runtime.context.tool_executor.execute_validated(
            ValidatedToolExecution(
                tool_name=tool_name,
                arguments=state.get("collected_arguments", {}),
                trusted_context=trusted,
            )
        )
    else:
        result = ToolExecutionResult(
            tool_name=tool_name,
            success=False,
            error_code=decision.reason_code,
            error_message=decision.reason_code,
            latency_ms=0,
        )
    if result.error_code == "ACCESS_DENIED":
        decision = AuthorizationDecision(
            allowed=False,
            reason_code="ACCESS_DENIED",
            source="odoo",
        )
    conversation = await runtime.context.conversation_service.load_owned(
        state["conversation_id"],
        int(state["trusted_context"]["odoo_user_id"]),
    )
    await runtime.context.conversation_service.update(
        conversation,
        status=(
            ConversationStatus.COMPLETED
            if result.success
            else ConversationStatus.FAILED
        ),
    )
    update = stage_update(
        state,
        event="tool_execution_completed",
        timing_name="odoo_execution_ms",
        started=started,
        data={
            "tool_name": tool_name,
            "success": result.success,
            "error_code": result.error_code,
        },
    )
    update["tool_result"] = result.model_dump(mode="json")
    update["authorization"] = decision.model_dump(mode="json")
    return update
