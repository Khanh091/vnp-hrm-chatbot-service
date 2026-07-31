from time import perf_counter

from langgraph.runtime import Runtime

from app.context.conversation import ConversationStatus
from app.context.entities import ResolvedSubject
from app.context.entity_memory import ConversationEntityMemory
from app.context.subject_resolver import SubjectResolution
from app.orchestration.context import GraphContext
from app.orchestration.nodes.common import routing_context_value, stage_update
from app.orchestration.state import ChatGraphState
from app.routing.schemas import QueryClassification
from app.routing.taxonomy import SubjectType
from app.security.authorization import AuthorizationDecision, AuthorizationRequest
from app.tools.definitions import (
    ToolExecutionResult,
    TrustedExecutionContext,
    ValidatedToolExecution,
)


def build_department_membership_result(
    data: object,
    *,
    actor_department_id: int | None,
    employee_name: str | None,
) -> dict[str, object]:
    payload = data if isinstance(data, dict) else {}
    department = payload.get("department")
    department_id = (
        department.get("id") if isinstance(department, dict) else None
    )
    department_name = (
        department.get("name") or department.get("display_name")
        if isinstance(department, dict)
        else None
    )
    return {
        "employee_name": employee_name,
        "is_member_of_actor_department": (
            department_id is not None
            and actor_department_id is not None
            and department_id == actor_department_id
        ),
        "employee_department": department_name,
    }


async def execute_read_tool_node(
    state: ChatGraphState, runtime: Runtime[GraphContext]
) -> dict[str, object]:
    started = perf_counter()
    tool_name = state["pending_tool_name"]
    assert tool_name is not None
    trusted = TrustedExecutionContext.model_validate(state["trusted_context"])
    classification = QueryClassification.model_validate(
        routing_context_value(state, "classification")
    )
    assert classification.intent is not None
    persisted_subject_resolution = state.get("workflow_data", {}).get(
        "subject_resolution"
    )
    resolved_subject = None
    if isinstance(persisted_subject_resolution, dict):
        subject_resolution = SubjectResolution.model_validate(
            persisted_subject_resolution
        )
        resolved_subject = subject_resolution.subject
    if resolved_subject is None and classification.scope.value == "self":
        resolved_subject = ResolvedSubject(
            type=SubjectType.SELF,
            employee_id=trusted.employee_id,
            source="trusted_context",
        )
    decision = runtime.context.authorization_policy.authorize(
        AuthorizationRequest(
            tool_name=tool_name,
            intent=classification.intent,
            operation=classification.operation,
            scope=classification.scope,
            trusted_context=trusted,
            resolved_subject=resolved_subject,
        ),
        allowed_tools={
            str(candidate["tool_name"])
            for candidate in (
                routing_context_value(state, "candidate_contexts") or []
            )
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
        if (
            result.success
            and tool_name == "employee_check_department_membership"
        ):
            result = result.model_copy(
                update={
                    "data": build_department_membership_result(
                        result.data,
                        actor_department_id=trusted.department_id,
                        employee_name=(
                            resolved_subject.employee_name
                            if resolved_subject is not None
                            else None
                        ),
                    )
                }
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
    entity_memory = ConversationEntityMemory.model_validate(
        state.get("entity_memory", {})
    )
    if result.success:
        entity_memory = runtime.context.entity_memory_service.capture(
            tool_name=tool_name,
            data=result.data,
            memory=entity_memory,
        )
    await runtime.context.conversation_service.update(
        conversation,
        status=(
            ConversationStatus.COMPLETED
            if result.success
            else ConversationStatus.FAILED
        ),
        entity_memory=entity_memory.model_dump(mode="json"),
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
    update["entity_memory"] = entity_memory.model_dump(mode="json")
    return update
