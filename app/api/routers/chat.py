import asyncio
import json
import logging
from collections.abc import AsyncIterator
from typing import Annotated, Any, Protocol, cast
from uuid import uuid4

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from app.api.schemas.chat import (
    ChatRequest,
    ChatResponse,
    StructuredAnswerType,
)
from app.api.schemas.common import ResponseMeta
from app.api.security import IngressUserDependency
from app.dependencies import OdooClientDependency, RequestIdDependency
from app.orchestration.nodes.common import (
    reset_graph_event_sink,
    set_graph_event_sink,
)
from app.orchestration.state import ChatPipelineResult
from app.tools.definitions import TrustedExecutionContext

router = APIRouter(
    prefix="/chat",
    tags=["Chat"],
)
logger = logging.getLogger(__name__)
_SSE_HEARTBEAT_SECONDS = 15.0


class ChatWorkflow(Protocol):
    async def process(
        self,
        message: str | None,
        trusted_context: TrustedExecutionContext,
        *,
        action_type: str | None = None,
        action_id: str | None = None,
        clarification: dict[str, Any] | None = None,
    ) -> ChatPipelineResult: ...


def get_chat_pipeline(request: Request) -> ChatWorkflow:
    return cast(ChatWorkflow, request.app.state.chat_pipeline)


ChatPipelineDependency = Annotated[ChatWorkflow, Depends(get_chat_pipeline)]


async def _trusted_context(
    *,
    ingress_user_id: int,
    odoo_client: OdooClientDependency,
    request_id: str,
    conversation_id: str | None,
) -> TrustedExecutionContext:
    odoo_context = await odoo_client.get_current_user_context(
        odoo_user_id=ingress_user_id,
        request_id=request_id,
    )
    return TrustedExecutionContext(
        odoo_user_id=odoo_context.user_id,
        employee_id=odoo_context.employee_id,
        company_id=odoo_context.company_id,
        department_id=odoo_context.department_id,
        company_ids=odoo_context.company_ids or (odoo_context.company_id,),
        group_codes=odoo_context.group_codes,
        capabilities=odoo_context.capabilities,
        timezone=odoo_context.timezone,
        language=odoo_context.language,
        conversation_id=conversation_id or str(uuid4()),
        request_id=request_id,
    )


async def _run_pipeline(
    pipeline: ChatWorkflow,
    request: ChatRequest,
    trusted_context: TrustedExecutionContext,
) -> ChatPipelineResult:
    answer = request.structured_answer
    if answer is not None and answer.type in {
        StructuredAnswerType.CONFIRM,
        StructuredAnswerType.CANCEL,
    }:
        return await pipeline.process(
            None,
            trusted_context,
            action_type=(
                "confirm"
                if answer.type is StructuredAnswerType.CONFIRM
                else "cancel"
                if answer.selected_value
                else "cancel_workflow"
            ),
            action_id=answer.selected_value,
        )
    if answer is not None and answer.type is StructuredAnswerType.PROFILE_FIELD_EDIT:
        return await pipeline.process(
            answer.display_label or str(answer.value or ""),
            trusted_context,
            clarification={
                "field": answer.field_key,
                "value": answer.value,
                "label": answer.display_label or str(answer.value or ""),
                "answer_type": answer.type.value,
                "slot_name": answer.field_key,
                "session_id": answer.session_id,
                "client_action_id": answer.client_action_id,
                "form_revision": answer.form_revision,
                "option_set_id": answer.option_set_id,
                "option_context": answer.option_context or {},
            },
        )
    if answer is not None and answer.type is StructuredAnswerType.PROFILE_EDIT_ACTION:
        return await pipeline.process(
            answer.action,
            trusted_context,
            clarification={
                "field": "profile_edit_action",
                "value": answer.action,
                "label": answer.action,
                "answer_type": answer.type.value,
                "slot_name": "profile_edit_action",
                "session_id": answer.session_id,
                "client_action_id": answer.client_action_id,
                "form_revision": answer.form_revision,
            },
        )
    if answer is not None:
        slot_name = answer.slot_name or ""
        internal_field = (
            "request_id" if slot_name == "leave_request_id" else slot_name
        )
        return await pipeline.process(
            answer.display_label,
            trusted_context,
            clarification={
                "field": internal_field,
                "value": answer.selected_value,
                "label": answer.display_label,
                "answer_type": answer.type.value,
                "slot_name": slot_name,
            },
        )
    return await pipeline.process(request.message, trusted_context)


@router.post("", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    ingress_user_id: IngressUserDependency,
    odoo_client: OdooClientDependency,
    request_id: RequestIdDependency,
    pipeline: ChatPipelineDependency,
) -> ChatResponse:
    trusted_context = await _trusted_context(
        ingress_user_id=ingress_user_id,
        odoo_client=odoo_client,
        request_id=request_id,
        conversation_id=request.conversation_id,
    )
    result = await _run_pipeline(pipeline, request, trusted_context)
    return ChatResponse(
        conversation_id=result.conversation_id,
        type=result.type,
        outcome=result.outcome,
        answer=result.answer,
        data=result.data,
        timings=result.timings,
        meta=ResponseMeta(request_id=request_id),
    )


def _sse(event: str, data: dict[str, Any]) -> str:
    payload = json.dumps(data, ensure_ascii=False, default=str)
    return f"event: {event}\ndata: {payload}\n\n"


def _status_event(event_type: str, message: str) -> str:
    return _sse(
        "status",
        {"type": event_type, "message": message},
    )


def _public_final(result: ChatPipelineResult) -> tuple[str, dict[str, Any]]:
    payload: dict[str, Any] = {
        "type": result.type.value,
        "conversation_id": result.conversation_id,
        "answer": result.answer,
    }
    if result.outcome is not None:
        payload["outcome"] = result.outcome.value
    data = result.data if isinstance(result.data, dict) else {}
    if result.type.value == "clarification_required":
        payload["data"] = {
            key: data[key]
            for key in ("message_type", "text", "clarification")
            if key in data
        }
        return "clarification", payload
    if result.type.value == "confirmation_required":
        # Profile CRUD stores the public card below ``data.confirmation``.
        # Keep that same shape on SSE as conversation history; flattening the
        # wrong level drops action_id and makes the live confirmation unusable
        # until the browser reloads the persisted conversation.
        confirmation = data.get("confirmation")
        if isinstance(confirmation, dict):
            safe_confirmation = {
                key: confirmation[key]
                for key in (
                    "action_id",
                    "action",
                    "operation",
                    "write_mode",
                    "title",
                    "summary",
                    "confirm_label",
                    "cancel_label",
                    "expires_at",
                )
                if key in confirmation
            }
            payload["data"] = {
                "message_type": "confirmation",
                "text": data.get("text") or result.answer,
                "confirmation": safe_confirmation,
            }
        else:
            # Retain the legacy flat confirmation contract.
            payload["data"] = {
                key: data[key]
                for key in (
                    "action_id",
                    "action",
                    "operation",
                    "write_mode",
                    "title",
                    "summary",
                    "confirm_label",
                    "cancel_label",
                    "expires_at",
                )
                if key in data
            }
        return "confirmation", payload
    if result.type.value == "error":
        if isinstance(data.get("error_code"), str):
            payload["data"] = {"error_code": data["error_code"]}
        return "error", payload
    return "answer", payload


_PUBLIC_GRAPH_EVENTS = {
    "query_classified": (
        "classification_completed",
        "Đã phân tích yêu cầu",
    ),
    "candidates_retrieved": (
        "tool_selection_started",
        "Đang xác định nghiệp vụ phù hợp",
    ),
    "tool_selected": (
        "tool_selection_completed",
        "Đã xác định nghiệp vụ",
    ),
    "selection_validated": (
        "tool_execution_started",
        "Đang tra cứu dữ liệu",
    ),
    "tool_execution_started": (
        "tool_execution_started",
        "Đang thực hiện yêu cầu",
    ),
    "tool_execution_completed": (
        "answer_generation_started",
        "Đang tạo câu trả lời",
    ),
}


async def _stream_events(
    pipeline: ChatWorkflow,
    chat_request: ChatRequest,
    trusted_context: TrustedExecutionContext,
) -> AsyncIterator[str]:
    queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()
    result_holder: list[ChatPipelineResult] = []
    failed = False
    answer_streamed = False

    async def produce() -> None:
        nonlocal failed
        token = set_graph_event_sink(queue.put_nowait)
        try:
            result_holder.append(
                await _run_pipeline(
                    pipeline,
                    chat_request,
                    trusted_context,
                )
            )
        except Exception:
            failed = True
            logger.exception(
                "chat_stream_pipeline_failed request_id=%s conversation_id=%s",
                trusted_context.request_id,
                trusted_context.conversation_id,
            )
        finally:
            reset_graph_event_sink(token)
            queue.put_nowait(None)

    yield _status_event("connected", "Đã kết nối")
    yield _status_event("processing", "Đang xử lý yêu cầu")
    yield _status_event(
        "classification_started",
        "Đang phân tích yêu cầu",
    )
    task = asyncio.create_task(produce())
    event_task: asyncio.Task[dict[str, Any] | None] | None = asyncio.create_task(
        queue.get()
    )
    try:
        while event_task is not None:
            done, _ = await asyncio.wait(
                (event_task,),
                timeout=_SSE_HEARTBEAT_SECONDS,
                return_when=asyncio.FIRST_COMPLETED,
            )
            if not done:
                yield ": keep-alive\n\n"
                continue
            graph_event = event_task.result()
            if graph_event is None:
                event_task = None
                break
            graph_event_type = str(graph_event.get("type"))
            if graph_event_type in {
                "answer_start",
                "answer_delta",
                "answer_done",
            }:
                answer_streamed = True
                yield _sse(
                    graph_event_type,
                    cast(dict[str, Any], graph_event.get("data") or {}),
                )
            public = _PUBLIC_GRAPH_EVENTS.get(graph_event_type)
            if public is not None:
                yield _status_event(*public)
            event_task = asyncio.create_task(queue.get())
        await task
    finally:
        if event_task is not None and not event_task.done():
            event_task.cancel()
            await asyncio.gather(event_task, return_exceptions=True)
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
    if failed or not result_holder:
        yield _sse(
            "error",
            {
                "type": "error",
                "conversation_id": trusted_context.conversation_id,
                "outcome": "invalid",
                "answer": "Thông tin bạn cung cấp chưa hợp lệ.",
            },
        )
        yield _sse(
            "done",
            {
                "type": "done",
                "conversation_id": trusted_context.conversation_id,
            },
        )
        return
    result = result_holder[0]
    if not (answer_streamed and result.type.value == "answer"):
        event, payload = _public_final(result)
        yield _sse(event, payload)
    yield _sse(
        "done",
        {
            "type": "done",
            "conversation_id": result.conversation_id,
        },
    )


@router.post("/stream")
async def chat_stream(
    request: ChatRequest,
    ingress_user_id: IngressUserDependency,
    odoo_client: OdooClientDependency,
    request_id: RequestIdDependency,
    pipeline: ChatPipelineDependency,
) -> StreamingResponse:
    trusted_context = await _trusted_context(
        ingress_user_id=ingress_user_id,
        odoo_client=odoo_client,
        request_id=request_id,
        conversation_id=request.conversation_id,
    )
    return StreamingResponse(
        _stream_events(pipeline, request, trusted_context),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
        },
    )
