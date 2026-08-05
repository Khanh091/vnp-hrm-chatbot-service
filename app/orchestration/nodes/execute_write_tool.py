import logging
from time import perf_counter
from uuid import uuid4

from langgraph.runtime import Runtime
from pydantic import ValidationError
from tenacity import (
    AsyncRetrying,
    retry_if_result,
    stop_after_attempt,
    wait_exponential,
)

from app.common.capability_outcomes import CapabilityOutcome
from app.context.conversation import ConversationStatus
from app.context.entities import ResolvedSubject
from app.integrations.odoo.profile_schema import ProfileSchemaError
from app.orchestration.context import GraphContext
from app.orchestration.nodes.common import stage_update
from app.orchestration.state import ChatGraphState, ChatResponseType
from app.routing.taxonomy import SubjectScope, SubjectType
from app.security.authorization import AuthorizationDecision, AuthorizationRequest
from app.tools.definitions import (
    ToolExecutionResult,
    TrustedExecutionContext,
    ValidatedToolExecution,
)

_TRANSIENT_CODES = {
    "ODOO_CONNECTION_ERROR",
    "CONNECTION_ERROR",
    "HTTP_502",
    "HTTP_503",
    "HTTP_504",
}

logger = logging.getLogger(__name__)


async def execute_write_tool_node(
    state: ChatGraphState, runtime: Runtime[GraphContext]
) -> dict[str, object]:
    started = perf_counter()
    action = state["pending_action"]
    persisted_action = await runtime.context.pending_action_service.load_owned(
        str(action["action_id"]),
        conversation_id=state["conversation_id"],
        odoo_user_id=int(state["trusted_context"]["odoo_user_id"]),
    )
    if persisted_action.tool_name == "profile_crud_workflow":
        return await _execute_profile_action(
            state, runtime, persisted_action, started
        )
    tool = runtime.context.tool_registry.get(persisted_action.tool_name)
    if not tool.enabled:
        raise RuntimeError("PENDING_TOOL_DISABLED")
    if tool.version != persisted_action.tool_version:
        raise RuntimeError("PENDING_TOOL_VERSION_MISMATCH")
    arguments = dict(persisted_action.validated_arguments)
    arguments["idempotency_key"] = persisted_action.idempotency_key
    trusted = TrustedExecutionContext.model_validate(state["trusted_context"])
    assert tool.intent is not None
    decision = runtime.context.authorization_policy.authorize(
        AuthorizationRequest(
            tool_name=tool.name,
            intent=tool.intent,
            operation=tool.query_operation,
            scope=SubjectScope.SELF,
            trusted_context=trusted,
            resolved_subject=ResolvedSubject(
                type=SubjectType.SELF,
                employee_id=trusted.employee_id,
                source="trusted_context",
            ),
        ),
        allowed_tools={persisted_action.tool_name},
        confirmation_granted=True,
    )
    if not decision.allowed:
        rejected_result = ToolExecutionResult(
            tool_name=tool.name,
            success=False,
            error_code=decision.reason_code,
            error_message=decision.reason_code,
            latency_ms=0,
        )
        await runtime.context.pending_action_service.finish(
            str(action["action_id"]),
            odoo_user_id=trusted.odoo_user_id,
            success=False,
            error_code=decision.reason_code,
            result_summary=None,
        )
        conversation = await runtime.context.conversation_service.load_owned(
            state["conversation_id"],
            trusted.odoo_user_id,
        )
        await runtime.context.conversation_service.update(
            conversation,
            status=ConversationStatus.FAILED,
        )
        update = stage_update(
            state,
            event="tool_execution_rejected",
            timing_name="odoo_execution_ms",
            started=started,
            data={"tool_name": tool.name, "reason_code": decision.reason_code},
        )
        update["tool_result"] = rejected_result.model_dump(mode="json")
        update["authorization"] = decision.model_dump(mode="json")
        return update
    try:
        validated = tool.argument_schema.model_validate(arguments)
    except ValidationError as error:
        raise RuntimeError("INVALID_PENDING_ACTION_ARGUMENTS") from error
    execution = ValidatedToolExecution(
        tool_name=tool.name,
        arguments=validated.model_dump(mode="json"),
        trusted_context=trusted,
        confirmation_granted=True,
    )
    result: ToolExecutionResult | None = None
    async for attempt in AsyncRetrying(
        retry=retry_if_result(
            lambda item: (
                isinstance(item, ToolExecutionResult)
                and item.error_code in _TRANSIENT_CODES
            )
        ),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=0.2, min=0.2, max=1),
        reraise=False,
    ):
        with attempt:
            result = await runtime.context.tool_executor.execute_validated(execution)
        attempt.retry_state.set_result(result)
    assert result is not None
    logger.info(
        "write_stage intent=%s tool_name=%s resolved_employee=%s "
        "selected_request_ref=%s changed_fields=%s odoo_error_code=%s",
        tool.intent.value,
        tool.name,
        trusted.employee_id,
        arguments.get("request_id"),
        sorted(arguments.get("changes", {})),
        result.error_code,
    )
    if result.error_code == "ACCESS_DENIED":
        decision = AuthorizationDecision(
            allowed=False,
            reason_code="ACCESS_DENIED",
            source="odoo",
        )
    await runtime.context.pending_action_service.finish(
        str(action["action_id"]),
        odoo_user_id=int(state["trusted_context"]["odoo_user_id"]),
        success=result.success,
        error_code=result.error_code,
        result_summary=(
            {"tool_name": tool.name, "success": result.success}
            if result.success
            else None
        ),
    )
    conversation = await runtime.context.conversation_service.load_owned(
        state["conversation_id"],
        int(state["trusted_context"]["odoo_user_id"]),
    )
    if not result.success and tool.name == "leave_update_request":
        metadata = persisted_action.display_summary
        snapshot = metadata.get("original_snapshot", {})
        await runtime.context.conversation_service.update(
            conversation,
            status=ConversationStatus.AWAITING_CLARIFICATION,
            pending_tool_name=tool.name,
            collected_arguments={
                "request_id": persisted_action.validated_arguments.get("request_id")
            },
            missing_arguments=["changes"],
            workflow_data={
                "actionable_loaded": True,
                "action": "update",
                "selected_request_ref": persisted_action.validated_arguments.get(
                    "request_id"
                ),
                "original_snapshot": snapshot,
                "last_failed_patch": metadata.get("validated_patch", {}),
                "last_error_code": result.error_code,
                "current_field": "changes",
            },
        )
    else:
        await runtime.context.conversation_service.update(
            conversation,
            status=(
                ConversationStatus.COMPLETED
                if result.success
                else ConversationStatus.FAILED
            ),
        )
    update = stage_update(
        state,
        event="tool_execution_completed",
        timing_name="odoo_execution_ms",
        started=started,
        data={
            "tool_name": tool.name,
            "success": result.success,
            "error_code": result.error_code,
        },
    )
    update["tool_result"] = result.model_dump(mode="json")
    update["authorization"] = decision.model_dump(mode="json")
    return update


async def _execute_profile_action(state, runtime, action, started):
    trusted = state["trusted_context"]
    actor = int(trusted["odoo_user_id"])
    arguments = dict(action.validated_arguments)
    arguments["idempotency_key"] = action.idempotency_key
    success = False
    error_code = None
    result_data = None
    try:
        if arguments.get("write_mode") == "approval_request":
            result = await runtime.context.profile_schema_client.execute_change_request(
                arguments, odoo_user_id=actor, request_id=state["request_id"]
            )
            result_data = result.model_dump(mode="json")
            if result.state != "wait" or not result.request_id:
                raise ProfileSchemaError(
                    "PROFILE_APPROVAL_WORKFLOW_FAILED",
                    "Odoo did not move the edition to the approval queue",
                )
        else:
            result_data = await runtime.context.profile_schema_client.execute_direct(
                arguments, odoo_user_id=actor, request_id=state["request_id"]
            )
        success = True
    except ProfileSchemaError as error:
        error_code = error.reason_code
    logger.info(
        "profile_edit_action conversation_id=%s session_id=%s "
        "action_type=confirm_submit resource_key=%s state_before=SUBMITTING "
        "state_after=%s draft_field_count=%s odoo_endpoint=%s result_code=%s",
        state["conversation_id"],
        action.display_summary.get("workflow_data", {}).get(
            "profile_edit_session_id"
        ),
        arguments.get("resource_key") or arguments.get("section_key"),
        "SUBMITTED" if success else "ERROR",
        len(arguments.get("changes", {})),
        "/api/hrm-chatbot/v1/profile/change-requests",
        "SUCCESS" if success else error_code,
    )
    await runtime.context.pending_action_service.finish(
        action.action_id, odoo_user_id=actor, success=success,
        error_code=error_code, result_summary=result_data,
    )
    conversation = await runtime.context.conversation_service.load_owned(
        state["conversation_id"], actor
    )
    if success:
        await runtime.context.conversation_service.update(
            conversation, status=ConversationStatus.COMPLETED,
        )
    else:
        workflow_data = dict(action.display_summary.get("workflow_data") or {})
        review = dict(action.display_summary.get("review") or {})
        review["form_revision"] = f"form-{uuid4()}"
        options = [
            {"value": "save_draft", "label": "Lưu nháp", "description": None},
            {"value": "submit", "label": "Gửi xác nhận", "description": None},
            {"value": "continue", "label": "Tiếp tục chỉnh sửa", "description": None},
            {"value": "cancel", "label": "Hủy thay đổi", "description": None},
        ]
        review["options"] = options
        workflow_data.update({
            "profile_edit_status": "REVIEWING",
            "profile_form_revision": review["form_revision"],
            "current_field": "profile_edit_action",
            "clarification_options": options,
            "clarification_metadata": review,
        })
        await runtime.context.conversation_service.update(
            conversation,
            status=ConversationStatus.AWAITING_CLARIFICATION,
            pending_tool_name="profile_crud_workflow",
            collected_arguments={},
            missing_arguments=["profile_edit_action"],
            ambiguous_arguments=[],
            workflow_data=workflow_data,
        )
    update = stage_update(
        state, event="profile_write_execution_completed",
        timing_name="odoo_execution_ms", started=started,
        data={"success": success, "error_code": error_code},
    )
    if success:
        approval = arguments.get("write_mode") == "approval_request"
        text = (
            "Yêu cầu điều chỉnh đã được tạo và đang chờ xử lý."
            if approval else "Thông tin hồ sơ đã được cập nhật."
        )
        update.update({
            "response_type": ChatResponseType.ANSWER,
            "capability_outcome": CapabilityOutcome.SUCCESS,
            "response_text": text,
            "response_data": {"result": result_data},
        })
    else:
        error_messages = {
            "PROFILE_RECORD_CHANGED": (
                "Dòng hồ sơ đã thay đổi sau khi bạn xác nhận. "
                "Vui lòng xem lại thông tin mới nhất."
            ),
            "PROFILE_RECORD_NOT_FOUND": (
                "Không tìm thấy dòng hồ sơ thuộc tài khoản hiện tại."
            ),
            "PROFILE_OPERATION_FORBIDDEN": (
                "Bạn không được phép thực hiện thao tác này."
            ),
            "PROFILE_INVALID_VALUE": "Giá trị hồ sơ không hợp lệ.",
        }
        update.update({
            "response_type": ChatResponseType.ERROR,
            "capability_outcome": CapabilityOutcome.INVALID,
            "response_text": error_messages.get(
                error_code, "Không thể thực hiện thay đổi hồ sơ."
            ),
            "response_data": {
                "error_code": error_code or "PROFILE_SUBMIT_FAILED",
                "retryable": True,
                "clarification": review,
            },
            "workflow_data": workflow_data,
            "pending_tool_name": "profile_crud_workflow",
            "missing_arguments": ["profile_edit_action"],
        })
    return update
