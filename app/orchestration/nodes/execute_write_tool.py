from time import perf_counter

from langgraph.runtime import Runtime
from pydantic import ValidationError
from tenacity import (
    AsyncRetrying,
    retry_if_result,
    stop_after_attempt,
    wait_exponential,
)

from app.context.conversation import ConversationStatus
from app.context.entities import ResolvedSubject
from app.orchestration.context import GraphContext
from app.orchestration.nodes.common import stage_update
from app.orchestration.state import ChatGraphState
from app.routing.taxonomy import SubjectScope
from app.security.authorization import AuthorizationDecision, AuthorizationRequest
from app.tools.definitions import (
    ToolExecutionResult,
    TrustedExecutionContext,
    ValidatedToolExecution,
)

_TRANSIENT_CODES = {
    "ODOO_CONNECTION_ERROR",
    "CONNECTION_ERROR",
    "HTTP_502",
    "HTTP_503",
    "HTTP_504",
}


async def execute_write_tool_node(
    state: ChatGraphState, runtime: Runtime[GraphContext]
) -> dict[str, object]:
    started = perf_counter()
    action = state["pending_action"]
    persisted_action = (
        await runtime.context.pending_action_service.load_owned(
            str(action["action_id"]),
            conversation_id=state["conversation_id"],
            odoo_user_id=int(state["trusted_context"]["odoo_user_id"]),
        )
    )
    tool = runtime.context.tool_registry.get(persisted_action.tool_name)
    if not tool.enabled:
        raise RuntimeError("PENDING_TOOL_DISABLED")
    if tool.version != persisted_action.tool_version:
        raise RuntimeError("PENDING_TOOL_VERSION_MISMATCH")
    arguments = dict(persisted_action.validated_arguments)
    arguments["idempotency_key"] = persisted_action.idempotency_key
    trusted = TrustedExecutionContext.model_validate(state["trusted_context"])
    assert tool.intent is not None
    decision = runtime.context.authorization_policy.authorize(
        AuthorizationRequest(
            tool_name=tool.name,
            intent=tool.intent,
            operation=tool.query_operation,
            scope=SubjectScope.SELF,
            trusted_context=trusted,
            resolved_subject=ResolvedSubject(
                scope=SubjectScope.SELF,
                employee_id=trusted.employee_id,
                source="trusted_context",
            ),
        ),
        allowed_tools={persisted_action.tool_name},
        confirmation_granted=True,
    )
    if not decision.allowed:
        rejected_result = ToolExecutionResult(
            tool_name=tool.name,
            success=False,
            error_code=decision.reason_code,
            error_message=decision.reason_code,
            latency_ms=0,
        )
        await runtime.context.pending_action_service.finish(
            str(action["action_id"]),
            odoo_user_id=trusted.odoo_user_id,
            success=False,
            error_code=decision.reason_code,
            result_summary=None,
        )
        conversation = await runtime.context.conversation_service.load_owned(
            state["conversation_id"],
            trusted.odoo_user_id,
        )
        await runtime.context.conversation_service.update(
            conversation,
            status=ConversationStatus.FAILED,
        )
        update = stage_update(
            state,
            event="tool_execution_rejected",
            timing_name="odoo_execution_ms",
            started=started,
            data={"tool_name": tool.name, "reason_code": decision.reason_code},
        )
        update["tool_result"] = rejected_result.model_dump(mode="json")
        update["authorization"] = decision.model_dump(mode="json")
        return update
    try:
        validated = tool.argument_schema.model_validate(arguments)
    except ValidationError as error:
        raise RuntimeError("INVALID_PENDING_ACTION_ARGUMENTS") from error
    execution = ValidatedToolExecution(
        tool_name=tool.name,
        arguments=validated.model_dump(mode="json"),
        trusted_context=trusted,
        confirmation_granted=True,
    )
    result: ToolExecutionResult | None = None
    async for attempt in AsyncRetrying(
        retry=retry_if_result(
            lambda item: (
                isinstance(item, ToolExecutionResult)
                and item.error_code in _TRANSIENT_CODES
            )
        ),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=0.2, min=0.2, max=1),
        reraise=False,
    ):
        with attempt:
            result = await runtime.context.tool_executor.execute_validated(
                execution
            )
        attempt.retry_state.set_result(result)
    assert result is not None
    if result.error_code == "ACCESS_DENIED":
        decision = AuthorizationDecision(
            allowed=False,
            reason_code="ACCESS_DENIED",
            source="odoo",
        )
    await runtime.context.pending_action_service.finish(
        str(action["action_id"]),
        odoo_user_id=int(state["trusted_context"]["odoo_user_id"]),
        success=result.success,
        error_code=result.error_code,
        result_summary=(
            {"tool_name": tool.name, "success": result.success}
            if result.success
            else None
        ),
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
            "tool_name": tool.name,
            "success": result.success,
            "error_code": result.error_code,
        },
    )
    update["tool_result"] = result.model_dump(mode="json")
    update["authorization"] = decision.model_dump(mode="json")
    return update
