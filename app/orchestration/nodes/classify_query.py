from time import perf_counter

from langgraph.runtime import Runtime

from app.orchestration.context import GraphContext
from app.orchestration.nodes.common import stage_update
from app.orchestration.state import ChatGraphState
from app.routing.schemas import NormalizedQuery


async def classify_query_node(
    state: ChatGraphState, runtime: Runtime[GraphContext]
) -> dict[str, object]:
    started = perf_counter()
    text = state.get("normalized_query") or ""
    result = await runtime.context.query_classifier.classify(
        NormalizedQuery(original_text=state.get("user_message") or text,
                        normalized_text=text)
    )
    update = stage_update(
        state,
        event="query_classified",
        timing_name="classification_ms",
        started=started,
        data={
            "route_type": result.route_type.value,
            "domain": result.primary_domain.value,
        },
    )
    update["classification"] = result.model_dump(mode="json")
    return update
