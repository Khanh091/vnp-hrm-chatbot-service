from time import perf_counter
from uuid import uuid4

from langgraph.runtime import Runtime

from app.common.error_messages import category_for_error, public_error_message
from app.orchestration.context import GraphContext
from app.orchestration.nodes.common import (
    emit_graph_event,
    routing_context_value,
    stage_update,
)
from app.orchestration.state import ChatGraphState, ChatResponseType
from app.routing.schemas import QueryClassification
from app.tools.definitions import ToolExecutionResult

_WRITE_SUCCESS = {
    "leave_create_request": "Đơn nghỉ phép đã được tạo thành công.",
    "leave_update_request": "Đơn nghỉ phép đã được cập nhật thành công.",
    "leave_cancel_request": "Đơn nghỉ phép đã được hủy thành công.",
}


async def format_response_node(
    state: ChatGraphState, runtime: Runtime[GraphContext]
) -> dict[str, object]:
    started = perf_counter()
    if state.get("response_type") is not None:
        return stage_update(
            state,
            event="response_ready",
            timing_name="response_formatting_ms",
            started=started,
        )
    result_data = state.get("tool_result")
    if not result_data:
        return {
            **stage_update(
                state,
                event="response_ready",
                timing_name="response_formatting_ms",
                started=started,
            ),
            "response_type": ChatResponseType.ERROR,
            "response_text": "Không thể hoàn tất yêu cầu.",
            "response_data": {"reason_code": "EMPTY_TOOL_RESULT"},
        }
    result = ToolExecutionResult.model_validate(result_data)
    if not result.success:
        response_type = ChatResponseType.ERROR
        category = category_for_error(result.error_code)
        text = public_error_message(result.error_code, category)
        data = {
            "tool_name": result.tool_name,
            "error_code": result.error_code,
            "category": category.value,
        }
    else:
        response_type = ChatResponseType.ANSWER
        write_text = _WRITE_SUCCESS.get(result.tool_name)
        if write_text is not None:
            text = write_text
        else:
            fallback_text = runtime.context.response_formatter.format(
                result.tool_name,
                result,
            )
            try:
                classification = QueryClassification.model_validate(
                    routing_context_value(state, "classification")
                )
                trusted = state["trusted_context"]
                context = runtime.context.answer_context_builder.build(
                    original_query=(
                        str(
                            state.get("workflow_data", {}).get(
                                "original_query"
                            )
                            or state.get("user_message")
                            or ""
                        )
                    ),
                    classification=classification,
                    tool_name=result.tool_name,
                    tool_result=result,
                    locale=str(trusted.get("language") or "vi_VN"),
                    timezone=str(trusted.get("timezone") or "Asia/Ho_Chi_Minh"),
                )
                message_id = str(uuid4())
                emit_graph_event(
                    "answer_start",
                    {"message_id": message_id},
                )
                chunks: list[str] = []
                async for chunk in runtime.context.final_answer_service.stream_answer(
                    context,
                    request_id=state["request_id"],
                ):
                    chunks.append(chunk)
                    emit_graph_event(
                        "answer_delta",
                        {"message_id": message_id, "delta": chunk},
                    )
                text = "".join(chunks).strip() or fallback_text
                emit_graph_event(
                    "answer_done",
                    {"message_id": message_id, "answer": text},
                )
            except (KeyError, TypeError, ValueError):
                text = fallback_text
        data = {"tool_name": result.tool_name, "result": result.data}
    update = stage_update(
        state,
        event="response_ready",
        timing_name="response_formatting_ms",
        started=started,
    )
    update.update(
        {
            "response_type": response_type,
            "response_text": text,
            "response_data": data,
        }
    )
    return update
