from time import perf_counter

from langgraph.runtime import Runtime

from app.orchestration.context import GraphContext
from app.orchestration.nodes.common import stage_update, trusted_today
from app.orchestration.state import (
    ChatGraphState,
    ChatResponseType,
    WorkflowStatus,
)
from app.routing.schemas import (
    QueryClassification,
    ToolCandidate,
    ToolSelectorRequest,
)
from app.routing.tool_selector import ToolSelectorError


async def select_tool_node(
    state: ChatGraphState, runtime: Runtime[GraphContext]
) -> dict[str, object]:
    started = perf_counter()
    candidates = [
        ToolCandidate.model_validate(item)
        for item in state.get("candidates", [])
    ]
    if not candidates:
        return {
            **stage_update(
                state,
                event="tool_selection_skipped",
                timing_name="tool_selection_ms",
                started=started,
            ),
            "workflow_status": WorkflowStatus.FAILED,
            "response_type": ChatResponseType.UNSUPPORTED,
            "response_text": "Yêu cầu này chưa có tool nghiệp vụ phù hợp.",
            "response_data": {"reason_code": "NO_CANDIDATES"},
            "pending_tool_name": None,
        }
    contexts = runtime.context.tool_selector.build_candidate_contexts(
        candidates
    )
    trusted = state["trusted_context"]
    try:
        selection = await runtime.context.tool_selector.select(
            ToolSelectorRequest(
                original_query=state.get("user_message") or "",
                normalized_query=state.get("normalized_query") or "",
                classification=QueryClassification.model_validate(
                    state["classification"]
                ),
                candidates=contexts,
                current_date=trusted_today(str(trusted["timezone"])),
                timezone=str(trusted["timezone"]),
            )
        )
    except ToolSelectorError:
        return {
            **stage_update(
                state,
                event="tool_selection_failed",
                timing_name="tool_selection_ms",
                started=started,
            ),
            "workflow_status": WorkflowStatus.FAILED,
            "response_type": ChatResponseType.ERROR,
            "response_text": "Không thể chọn tool an toàn cho yêu cầu này.",
            "response_data": {"reason_code": "TOOL_SELECTION_FAILED"},
            "pending_tool_name": None,
        }
    selected = selection.selected_tool
    update = stage_update(
        state,
        event="tool_selected",
        timing_name="tool_selection_ms",
        started=started,
        data={"tool_name": selected},
    )
    update.update(
        {
            "selection": selection.model_dump(mode="json"),
            "candidate_contexts": [
                item.model_dump(mode="json") for item in contexts
            ],
            "pending_tool_name": selected,
        }
    )
    if selected is None:
        update.update(
            {
                "workflow_status": WorkflowStatus.FAILED,
                "response_type": ChatResponseType.UNSUPPORTED,
                "response_text": "Không tìm thấy tool phù hợp với yêu cầu.",
                "response_data": {"reason_code": selection.reason_code},
            }
        )
    return update
