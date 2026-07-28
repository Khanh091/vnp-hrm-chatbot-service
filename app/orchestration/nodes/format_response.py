from time import perf_counter

from langgraph.runtime import Runtime

from app.orchestration.context import GraphContext
from app.orchestration.nodes.common import stage_update
from app.orchestration.state import ChatGraphState, ChatResponseType
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
        update = stage_update(
            state,
            event="response_ready",
            timing_name="response_formatting_ms",
            started=started,
        )
        return update
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
        text = "Không thể thực hiện yêu cầu HRM lúc này."
        data = {
            "tool_name": result.tool_name,
            "error_code": result.error_code,
        }
    else:
        response_type = ChatResponseType.ANSWER
        text = _WRITE_SUCCESS.get(
            result.tool_name,
            runtime.context.response_formatter.format(
                result.tool_name, result
            ),
        )
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
