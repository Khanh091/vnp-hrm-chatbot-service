from time import perf_counter

from langgraph.runtime import Runtime

from app.orchestration.context import GraphContext
from app.orchestration.nodes.common import stage_update
from app.orchestration.state import ChatGraphState, ChatResponseType, WorkflowStatus
from app.routing.candidate_retriever import RoutingInvariantError
from app.routing.schemas import (
    CandidateRetrievalRequest,
    QueryClassification,
)


async def retrieve_candidates_node(
    state: ChatGraphState, runtime: Runtime[GraphContext]
) -> dict[str, object]:
    started = perf_counter()
    settings = runtime.context.settings
    try:
        outcome = await runtime.context.candidate_retriever.retrieve(
            CandidateRetrievalRequest(
                query=state.get("normalized_query") or "",
                classification=QueryClassification.model_validate(
                    state["classification"]
                ),
                top_k=settings.tool_top_k,
                fetch_k=settings.tool_fetch_k,
                min_score=settings.tool_min_score,
            )
        )
    except RoutingInvariantError as error:
        return {
            **stage_update(
                state,
                event="routing_invariant_failed",
                timing_name="candidate_retrieval_ms",
                started=started,
                data={"reason_code": error.reason_code},
            ),
            "workflow_status": WorkflowStatus.FAILED,
            "response_type": ChatResponseType.ERROR,
            "response_text": "Không thể định tuyến yêu cầu một cách an toàn.",
            "response_data": {"reason_code": error.reason_code},
            "workflow_issues": [{"code": error.reason_code}],
        }
    update = stage_update(
        state,
        event="candidates_retrieved",
        timing_name="candidate_retrieval_ms",
        started=started,
        data={"count": len(outcome.candidates)},
    )
    update["candidates"] = [
        item.model_dump(mode="json") for item in outcome.candidates
    ]
    return update
