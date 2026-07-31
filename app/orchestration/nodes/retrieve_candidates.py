from time import perf_counter

from langgraph.runtime import Runtime

from app.common.capability_outcomes import (
    CapabilityOutcome,
    capability_label_for_intent,
    public_outcome_message,
)
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
        classification = QueryClassification.model_validate(
            state["classification"]
        )
        capability_outcome = CapabilityOutcome.UNSUPPORTED
        return {
            **stage_update(
                state,
                event="routing_invariant_failed",
                timing_name="candidate_retrieval_ms",
                started=started,
                data={"reason_code": error.reason_code},
            ),
            "workflow_status": WorkflowStatus.FAILED,
            "response_type": ChatResponseType.UNSUPPORTED,
            "capability_outcome": capability_outcome,
            "response_text": public_outcome_message(
                capability_outcome,
                capability_label=capability_label_for_intent(
                    classification.intent
                ),
            ),
            "response_data": None,
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
    update["candidate_resolution_reason"] = outcome.fallback_reason
    return update
