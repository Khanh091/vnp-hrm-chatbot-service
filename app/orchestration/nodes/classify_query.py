from time import perf_counter

from langgraph.runtime import Runtime

from app.orchestration.context import GraphContext
from app.orchestration.nodes.common import stage_update
from app.orchestration.state import (
    ChatGraphState,
    ChatResponseType,
    WorkflowStatus,
)
from app.routing.query_classifier import QueryClassifierError


async def classify_query_node(
    state: ChatGraphState, runtime: Runtime[GraphContext]
) -> dict[str, object]:
    started = perf_counter()
    text = state.get("normalized_query") or ""
    try:
        result = await runtime.context.query_classifier.classify(
            runtime.context.query_normalizer.normalize(
                state.get("user_message") or text
            )
        )
    except QueryClassifierError as error:
        answer = {
            "LLM_RATE_LIMITED": (
                "Hệ thống AI đang tạm thời đạt giới hạn xử lý. "
                "Vui lòng thử lại sau."
            ),
            "LLM_BAD_RESPONSE": (
                "Hệ thống chưa phân tích được yêu cầu này. "
                "Vui lòng diễn đạt lại ngắn gọn hơn."
            ),
            "LLM_TIMEOUT": (
                "Hệ thống AI phản hồi quá chậm. Vui lòng thử lại sau."
            ),
            "ROUTING_SCOPE_NOT_SUPPORTED": (
                "Tôi chưa xác định chính xác đối tượng bạn muốn tra cứu."
            ),
        }.get(
            error.reason_code,
            "Hệ thống AI tạm thời chưa sẵn sàng. Vui lòng thử lại sau.",
        )
        return {
            **stage_update(
                state,
                event="query_classification_failed",
                timing_name="classification_ms",
                started=started,
                data={"reason_code": error.reason_code},
            ),
            "workflow_status": WorkflowStatus.FAILED,
            "response_type": ChatResponseType.ERROR,
            "response_text": answer,
            "response_data": {
                "stage": "classification",
                "reason_code": error.reason_code,
            },
            "pending_tool_name": None,
            "missing_arguments": [],
            "ambiguous_arguments": [],
            "workflow_data": {},
        }
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
