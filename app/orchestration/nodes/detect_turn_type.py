from time import perf_counter

from langgraph.runtime import Runtime

from app.context.conversation import ConversationStatus
from app.orchestration.context import GraphContext
from app.orchestration.nodes.common import stage_update
from app.orchestration.state import ChatGraphState, TurnType


async def detect_turn_type_node(
    state: ChatGraphState, runtime: Runtime[GraphContext]
) -> dict[str, object]:
    del runtime
    started = perf_counter()
    action_type = state.get("action_type")
    if action_type == "confirm":
        turn_type = TurnType.CONFIRMATION_ACCEPT
    elif action_type == "cancel":
        turn_type = TurnType.CONFIRMATION_CANCEL
    elif (
        state.get("conversation_status")
        == ConversationStatus.AWAITING_CLARIFICATION.value
    ):
        turn_type = TurnType.CLARIFICATION_ANSWER
    else:
        turn_type = TurnType.NEW_QUERY
    update = stage_update(
        state,
        event="turn_detected",
        timing_name="turn_detection_ms",
        started=started,
        data={"turn_type": turn_type.value},
    )
    update["turn_type"] = turn_type
    return update
