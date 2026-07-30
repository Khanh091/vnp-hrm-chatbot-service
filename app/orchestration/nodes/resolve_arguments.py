from time import perf_counter

from langgraph.runtime import Runtime

from app.context.entity_memory import ConversationEntityMemory
from app.orchestration.context import GraphContext
from app.orchestration.nodes.common import stage_update, trusted_today
from app.orchestration.state import ChatGraphState
from app.routing.schemas import ToolSelection
from app.routing.taxonomy import SubjectType
from app.tools.definitions import TrustedExecutionContext


async def resolve_arguments_node(
    state: ChatGraphState, runtime: Runtime[GraphContext]
) -> dict[str, object]:
    started = perf_counter()
    tool_name = state.get("pending_tool_name")
    if not tool_name:
        return stage_update(
            state,
            event="argument_resolution_skipped",
            timing_name="argument_resolution_ms",
            started=started,
        )
    tool = runtime.context.tool_registry.get(tool_name)
    selection = ToolSelection.model_validate(state["selection"])
    trusted = state["trusted_context"]
    trusted_context = TrustedExecutionContext.model_validate(trusted)
    query_text = (
        ""
        if state.get("turn_type") == "clarification_answer"
        else state.get("normalized_query") or ""
    )
    resolution = runtime.context.argument_resolver.resolve(
        selection,
        tool,
        query=query_text,
        current_date=trusted_today(str(trusted["timezone"])),
        timezone=str(trusted["timezone"]),
        conversation_arguments=state.get("collected_arguments"),
    )
    subject_mention = runtime.context.entity_resolver.extract_subject(
        query_text or state.get("user_message") or ""
    )
    subject_resolution = None
    if subject_mention.type in {
        SubjectType.SELF,
        SubjectType.EMPLOYEE,
        SubjectType.DEPARTMENT,
    }:
        subject_resolution = await runtime.context.subject_resolver.resolve(
            subject_mention,
            trusted_context.actor_context,
        )
    resolved_arguments = dict(resolution.arguments)
    if (
        "request_id" in tool.argument_schema.model_fields
        and "request_id" not in resolved_arguments
    ):
        mention = runtime.context.entity_resolver.extract_subject(
            state.get("normalized_query") or state.get("user_message") or ""
        )
        reference = runtime.context.entity_memory_service.resolve_leave_request(
            mention,
            ConversationEntityMemory.model_validate(
                state.get("entity_memory", {})
            ),
        )
        if reference is not None:
            try:
                resolved_arguments["request_id"] = int(reference.entity_id)
            except (TypeError, ValueError):
                pass
    workflow = runtime.context.workflow_registry.get(tool_name)
    slot_issues: list[dict[str, object]] = []
    if workflow is not None:
        slot_state = runtime.context.slot_manager.initialize(
            workflow,
            resolved_arguments,
        )
        arguments = slot_state.values
        missing = slot_state.missing
        ambiguous = list(
            dict.fromkeys(
                [*resolution.ambiguous_arguments, *slot_state.ambiguous]
            )
        )
        slot_issues = [
            issue.model_dump(mode="json") for issue in slot_state.issues
        ]
    else:
        arguments = resolved_arguments
        missing = resolution.missing_arguments
        ambiguous = resolution.ambiguous_arguments
    update = stage_update(
        state,
        event="arguments_resolved",
        timing_name="argument_resolution_ms",
        started=started,
    )
    update.update(
        {
            "collected_arguments": arguments,
            "missing_arguments": missing,
            "ambiguous_arguments": ambiguous,
            "workflow_data": {
                **state.get("workflow_data", {}),
                "transient_entities": resolution.transient_entities,
                "slot_issues": slot_issues,
                "rejected_trusted_fields": (
                    resolution.rejected_trusted_fields
                ),
                "subject_mention": subject_mention.model_dump(mode="json"),
                "subject_resolution": (
                    subject_resolution.model_dump(mode="json")
                    if subject_resolution is not None
                    else state.get("workflow_data", {}).get(
                        "subject_resolution"
                    )
                ),
            },
        }
    )
    return update
