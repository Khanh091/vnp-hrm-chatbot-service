from __future__ import annotations

from datetime import date, datetime
from time import perf_counter
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.common.capability_outcomes import (
    CapabilityOutcome,
    capability_label_for_intent,
    outcome_for_error,
    outcome_for_success,
    public_outcome_message,
)
from app.context.conversation import (
    ClarificationRequiredData,
    ConfirmationRequiredData,
    ConversationStore,
)
from app.orchestration.state import (
    ChatPipelineResult,
    ChatResponseType,
    ChatStageTimings,
)
from app.routing.argument_resolver import ArgumentResolver
from app.routing.schemas import (
    RouteType,
    ToolSelectorRequest,
)
from app.routing.service import RoutingService
from app.routing.tool_selector import ToolSelector, ToolSelectorError
from app.routing.validator import ToolSelectionValidator
from app.tools.definitions import (
    TrustedExecutionContext,
    ValidatedToolExecution,
)
from app.tools.executor import ToolExecutor
from app.tools.registry import ToolRegistry
from app.tools.response_formatter import ToolResponseFormatter


class ChatPipeline:
    def __init__(
        self,
        routing_service: RoutingService,
        selector: ToolSelector,
        argument_resolver: ArgumentResolver,
        validator: ToolSelectionValidator,
        executor: ToolExecutor,
        formatter: ToolResponseFormatter,
        conversation_store: ConversationStore,
        registry: ToolRegistry,
    ) -> None:
        self._routing = routing_service
        self._selector = selector
        self._argument_resolver = argument_resolver
        self._validator = validator
        self._executor = executor
        self._formatter = formatter
        self._conversation_store = conversation_store
        self._registry = registry

    @property
    def routing_service(self) -> RoutingService:
        return self._routing

    async def process(
        self,
        message: str,
        trusted_context: TrustedExecutionContext,
    ) -> ChatPipelineResult:
        total_started = perf_counter()
        timings: dict[str, float] = {}
        routing = await self._routing.route(message)
        timings["classification_ms"] = routing.timings.classification_ms
        timings["candidate_retrieval_ms"] = (
            routing.timings.embedding_ms + routing.timings.vector_search_ms
        )
        if (
            routing.classification.route_type
            in {
                RouteType.UNSUPPORTED,
                RouteType.GENERAL_CHAT,
                RouteType.DOCUMENT_QA,
                RouteType.NAVIGATION,
                RouteType.EMPLOYEE_SEARCH,
            }
            or not routing.candidates
        ):
            outcome = CapabilityOutcome.UNSUPPORTED
            return self._result(
                trusted_context.conversation_id,
                ChatResponseType.UNSUPPORTED,
                public_outcome_message(
                    outcome,
                    capability_label=capability_label_for_intent(
                        routing.classification.intent
                    ),
                ),
                None,
                timings,
                total_started,
                outcome,
            )

        contexts = self._selector.build_candidate_contexts(routing.candidates)
        conversation = await self._conversation_store.get_context(
            trusted_context.conversation_id
        )
        current_date = self._trusted_current_date(trusted_context.timezone)
        selector_request = ToolSelectorRequest(
            original_query=message,
            normalized_query=routing.normalized_query,
            classification=routing.classification,
            candidates=contexts,
            conversation_context=conversation,
            current_date=current_date,
            timezone=trusted_context.timezone,
        )
        started = perf_counter()
        try:
            selection = await self._selector.select(selector_request)
        except ToolSelectorError:
            timings["tool_selection_ms"] = self._elapsed(started)
            outcome = CapabilityOutcome.INVALID
            return self._result(
                trusted_context.conversation_id,
                ChatResponseType.ERROR,
                public_outcome_message(outcome),
                None,
                timings,
                total_started,
                outcome,
            )
        timings["tool_selection_ms"] = self._elapsed(started)
        if selection.selected_tool is None:
            outcome = CapabilityOutcome.UNSUPPORTED
            return self._result(
                trusted_context.conversation_id,
                ChatResponseType.UNSUPPORTED,
                public_outcome_message(
                    outcome,
                    capability_label=capability_label_for_intent(
                        routing.classification.intent
                    ),
                ),
                None,
                timings,
                total_started,
                outcome,
            )

        tool = self._registry.get(selection.selected_tool)
        started = perf_counter()
        resolution = self._argument_resolver.resolve(
            selection,
            tool,
            query=routing.normalized_query,
            current_date=current_date,
            timezone=trusted_context.timezone,
            conversation_arguments=(
                conversation.collected_arguments
                if conversation and conversation.pending_tool == tool.name
                else None
            ),
        )
        timings["argument_resolution_ms"] = self._elapsed(started)

        started = perf_counter()
        validation = self._validator.validate(
            selection,
            resolution,
            classification=routing.classification,
            candidates=contexts,
        )
        timings["validation_ms"] = self._elapsed(started)

        if validation.requires_clarification:
            question = (
                resolution.clarification_question
                or selection.clarification_question
                or "Bạn có thể cung cấp thêm thông tin cho yêu cầu này?"
            )
            await self._conversation_store.save_clarification(
                conversation_id=trusted_context.conversation_id,
                pending_tool=tool.name,
                collected_arguments=resolution.arguments,
                last_user_message=message,
            )
            data = ClarificationRequiredData(
                pending_tool=tool.name,
                missing_arguments=resolution.missing_arguments,
                collected_arguments=self._public_arguments(
                    resolution.arguments
                ),
                question=question,
            )
            return self._result(
                trusted_context.conversation_id,
                ChatResponseType.CLARIFICATION_REQUIRED,
                question,
                data.model_dump(mode="json"),
                timings,
                total_started,
            )

        if not validation.valid:
            low_confidence = any(
                issue.code
                in {
                    "LOW_CONFIDENCE",
                    "ROUTING_AMBIGUOUS",
                }
                for issue in validation.errors
            )
            return self._result(
                trusted_context.conversation_id,
                (
                    ChatResponseType.CLARIFICATION_REQUIRED
                    if low_confidence
                    else ChatResponseType.ERROR
                ),
                (
                    "Bạn có thể nói rõ hơn mục tiêu cần tra cứu?"
                    if low_confidence
                    else "Thông tin đầu vào chưa hợp lệ."
                ),
                None,
                timings,
                total_started,
                (
                    None
                    if low_confidence
                    else CapabilityOutcome.INVALID
                ),
            )

        if validation.requires_confirmation:
            action = await self._conversation_store.create_pending_action(
                conversation_id=trusted_context.conversation_id,
                user_id=trusted_context.odoo_user_id,
                tool_name=tool.name,
                validated_arguments=validation.normalized_arguments,
            )
            confirmation = ConfirmationRequiredData(
                action_id=action.action_id,
                tool_name=tool.name,
                title=self._confirmation_title(tool.name),
                summary=self._public_arguments(
                    validation.normalized_arguments
                ),
                expires_at=action.expires_at,
            )
            return self._result(
                trusted_context.conversation_id,
                ChatResponseType.CONFIRMATION_REQUIRED,
                confirmation.title,
                confirmation.model_dump(mode="json"),
                timings,
                total_started,
            )

        started = perf_counter()
        execution = await self._executor.execute_validated(
            ValidatedToolExecution(
                tool_name=tool.name,
                arguments=validation.normalized_arguments,
                trusted_context=trusted_context,
            )
        )
        timings["execution_ms"] = self._elapsed(started)
        if not execution.success:
            outcome = outcome_for_error(execution.error_code)
            return self._result(
                trusted_context.conversation_id,
                ChatResponseType.ERROR,
                public_outcome_message(outcome),
                None,
                timings,
                total_started,
                outcome,
            )

        started = perf_counter()
        outcome = outcome_for_success(execution.data)
        answer = (
            public_outcome_message(outcome)
            if outcome is CapabilityOutcome.EMPTY
            else self._formatter.format(tool.name, execution)
        )
        timings["response_formatting_ms"] = self._elapsed(started)
        await self._conversation_store.clear_context(
            trusted_context.conversation_id
        )
        return self._result(
            trusted_context.conversation_id,
            ChatResponseType.ANSWER,
            answer,
            {"result": execution.data},
            timings,
            total_started,
            outcome,
        )

    async def preview(self, message: str) -> dict[str, Any]:
        routing = await self._routing.route(message)
        contexts = self._selector.build_candidate_contexts(routing.candidates)
        if not contexts:
            return {
                "classification": routing.classification.model_dump(mode="json"),
                "candidates": [],
                "selection": None,
                "validation": None,
                "execution_skipped": True,
            }
        today = datetime.now().date()
        selection = await self._selector.select(
            ToolSelectorRequest(
                original_query=message,
                normalized_query=routing.normalized_query,
                classification=routing.classification,
                candidates=contexts,
                current_date=today,
                timezone="Asia/Ho_Chi_Minh",
            )
        )
        validation = None
        if selection.selected_tool:
            tool = self._registry.get(selection.selected_tool)
            resolution = self._argument_resolver.resolve(
                selection,
                tool,
                query=routing.normalized_query,
                current_date=today,
                timezone="Asia/Ho_Chi_Minh",
            )
            validation = self._validator.validate(
                selection,
                resolution,
                classification=routing.classification,
                candidates=contexts,
            )
        return {
            "classification": routing.classification.model_dump(mode="json"),
            "candidates": [
                candidate.model_dump(mode="json")
                for candidate in routing.candidates
            ],
            "selection": selection.model_dump(mode="json"),
            "validation": (
                validation.model_dump(mode="json") if validation else None
            ),
            "execution_skipped": True,
        }

    @staticmethod
    def _trusted_current_date(timezone_name: str) -> date:
        try:
            zone = ZoneInfo(timezone_name)
        except ZoneInfoNotFoundError:
            zone = ZoneInfo("UTC")
        return datetime.now(zone).date()

    @staticmethod
    def _elapsed(started: float) -> float:
        return max(0.0, (perf_counter() - started) * 1000)

    @staticmethod
    def _public_arguments(arguments: dict[str, Any]) -> dict[str, Any]:
        hidden = {"idempotency_key", "odoo_user_id"}
        return {
            key: value
            for key, value in arguments.items()
            if key not in hidden
        }

    @staticmethod
    def _confirmation_title(tool_name: str) -> str:
        titles = {
            "leave_create_request": "Xác nhận tạo đơn nghỉ phép",
            "leave_update_request": "Xác nhận cập nhật đơn nghỉ phép",
            "leave_cancel_request": "Xác nhận hủy đơn nghỉ phép",
        }
        return titles.get(tool_name, "Xác nhận thao tác")

    @staticmethod
    def _result(
        conversation_id: str,
        response_type: ChatResponseType,
        answer: str | None,
        data: dict[str, Any] | None,
        timings: dict[str, float],
        total_started: float,
        outcome: CapabilityOutcome | None = None,
    ) -> ChatPipelineResult:
        timings["total_ms"] = ChatPipeline._elapsed(total_started)
        return ChatPipelineResult(
            conversation_id=conversation_id,
            type=response_type,
            outcome=outcome,
            answer=answer,
            data=data,
            timings=ChatStageTimings.model_validate(timings),
        )
