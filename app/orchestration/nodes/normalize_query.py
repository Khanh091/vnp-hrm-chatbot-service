from time import perf_counter

from langgraph.runtime import Runtime

from app.orchestration.context import GraphContext
from app.orchestration.nodes.common import stage_update
from app.orchestration.state import ChatGraphState


async def normalize_query_node(
    state: ChatGraphState, runtime: Runtime[GraphContext]
) -> dict[str, object]:
    started = perf_counter()
    normalized = runtime.context.query_normalizer.normalize(
        state.get("user_message") or ""
    )
    update = stage_update(
        state,
        event="query_normalized",
        timing_name="normalization_ms",
        started=started,
    )
    update["normalized_query"] = normalized.normalized_text
    return update
