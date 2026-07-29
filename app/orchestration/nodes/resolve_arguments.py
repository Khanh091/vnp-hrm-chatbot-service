from time import perf_counter

from langgraph.runtime import Runtime

from app.orchestration.context import GraphContext
from app.orchestration.nodes.common import stage_update, trusted_today
from app.orchestration.state import ChatGraphState
from app.routing.schemas import ToolSelection


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
    resolution = runtime.context.argument_resolver.resolve(
        selection,
        tool,
        query=(
            ""
            if state.get("turn_type") == "clarification_answer"
            else state.get("normalized_query") or ""
        ),
        current_date=trusted_today(str(trusted["timezone"])),
        timezone=str(trusted["timezone"]),
        conversation_arguments=state.get("collected_arguments"),
    )
    workflow = runtime.context.workflow_registry.get(tool_name)
    slot_issues: list[dict[str, object]] = []
    if workflow is not None:
        slot_state = runtime.context.slot_manager.initialize(
            workflow,
            resolution.arguments,
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
        arguments = resolution.arguments
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
            },
        }
    )
    return update
