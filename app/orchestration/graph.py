from __future__ import annotations

from datetime import datetime
from time import perf_counter
from typing import Any

from langgraph.errors import GraphRecursionError
from langgraph.graph import END, START, StateGraph

from app.common.capability_outcomes import (
    outcome_for_error,
    public_outcome_message,
)
from app.context.conversation_service import ConversationStateError
from app.context.pending_action_service import PendingActionError
from app.orchestration.context import GraphContext
from app.orchestration.nodes.ask_clarification import ask_clarification_node
from app.orchestration.nodes.cancel_pending_action import (
    cancel_pending_action_node,
)
from app.orchestration.nodes.classify_query import classify_query_node
from app.orchestration.nodes.create_confirmation import (
    create_confirmation_node,
)
from app.orchestration.nodes.detect_turn_type import detect_turn_type_node
from app.orchestration.nodes.execute_read_tool import execute_read_tool_node
from app.orchestration.nodes.execute_write_tool import execute_write_tool_node
from app.orchestration.nodes.format_response import format_response_node
from app.orchestration.nodes.load_conversation import load_conversation_node
from app.orchestration.nodes.load_pending_action import (
    load_pending_action_cancel_node,
    load_pending_action_confirm_node,
)
from app.orchestration.nodes.merge_clarification import (
    merge_clarification_node,
)
from app.orchestration.nodes.normalize_query import normalize_query_node
from app.orchestration.nodes.persist_conversation import (
    persist_conversation_node,
)
from app.orchestration.nodes.resolve_arguments import resolve_arguments_node
from app.orchestration.nodes.resolve_profile_write import resolve_profile_write_node
from app.orchestration.nodes.retrieve_candidates import (
    retrieve_candidates_node,
)
from app.orchestration.nodes.select_tool import select_tool_node
from app.orchestration.nodes.validate_selection import (
    validate_selection_node,
)
from app.orchestration.routes import (
    route_after_argument_resolution,
    route_after_clarification_merge,
    route_after_classification,
    route_after_retrieval,
    route_after_selection,
    route_after_turn_detection,
    route_after_validation,
)
from app.orchestration.state import (
    ChatGraphState,
    ChatPipelineResult,
    ChatResponseType,
    ChatStageTimings,
)
from app.routing.schemas import ToolSelectorRequest
from app.tools.definitions import TrustedExecutionContext


def build_chat_graph(checkpointer: Any = None) -> Any:
    builder = StateGraph(ChatGraphState, context_schema=GraphContext)
    builder.add_node("load_conversation", load_conversation_node)
    builder.add_node("detect_turn_type", detect_turn_type_node)
    builder.add_node("normalize_query", normalize_query_node)
    builder.add_node("classify_query", classify_query_node)
    builder.add_node("retrieve_candidates", retrieve_candidates_node)
    builder.add_node("select_tool", select_tool_node)
    builder.add_node("merge_clarification", merge_clarification_node)
    builder.add_node("resolve_arguments", resolve_arguments_node)
    builder.add_node("resolve_profile_write", resolve_profile_write_node)
    builder.add_node("validate_selection", validate_selection_node)
    builder.add_node("ask_clarification", ask_clarification_node)
    builder.add_node("create_confirmation", create_confirmation_node)
    builder.add_node(
        "load_pending_action_confirm", load_pending_action_confirm_node
    )
    builder.add_node(
        "load_pending_action_cancel", load_pending_action_cancel_node
    )
    builder.add_node("cancel_pending_action", cancel_pending_action_node)
    builder.add_node("execute_read_tool", execute_read_tool_node)
    builder.add_node("execute_write_tool", execute_write_tool_node)
    builder.add_node("format_response", format_response_node)
    builder.add_node("persist_conversation", persist_conversation_node)

    builder.add_edge(START, "load_conversation")
    builder.add_edge("load_conversation", "detect_turn_type")
    builder.add_conditional_edges(
        "detect_turn_type", route_after_turn_detection
    )
    builder.add_edge("normalize_query", "classify_query")
    builder.add_conditional_edges(
        "classify_query", route_after_classification
    )
    builder.add_conditional_edges(
        "retrieve_candidates",
        route_after_retrieval,
    )
    builder.add_conditional_edges("select_tool", route_after_selection)
    builder.add_conditional_edges(
        "merge_clarification",
        route_after_clarification_merge,
    )
    builder.add_conditional_edges(
        "resolve_arguments", route_after_argument_resolution
    )
    builder.add_conditional_edges(
        "validate_selection", route_after_validation
    )
    builder.add_edge(
        "load_pending_action_confirm", "execute_write_tool"
    )
    builder.add_edge(
        "load_pending_action_cancel", "cancel_pending_action"
    )
    for node in (
        "ask_clarification",
        "resolve_profile_write",
        "create_confirmation",
        "cancel_pending_action",
        "execute_read_tool",
        "execute_write_tool",
    ):
        builder.add_edge(node, "format_response")
    builder.add_edge("format_response", "persist_conversation")
    builder.add_edge("persist_conversation", END)
    return builder.compile(checkpointer=checkpointer)


class ChatGraphWorkflow:
    def __init__(
        self,
        context: GraphContext,
        *,
        checkpointer: Any = None,
    ) -> None:
        self._context = context
        self._graph = build_chat_graph(checkpointer)

    @property
    def routing_service(self) -> None:
        return None

    async def process(
        self,
        message: str | None,
        trusted_context: TrustedExecutionContext,
        *,
        action_type: str | None = None,
        action_id: str | None = None,
        clarification: dict[str, Any] | None = None,
    ) -> ChatPipelineResult:
        started = perf_counter()
        initial: ChatGraphState = {
            "conversation_id": trusted_context.conversation_id,
            "request_id": trusted_context.request_id,
            "user_message": message,
            "action_type": action_type,
            "action_id": action_id,
            "clarification": clarification,
            "trusted_context": trusted_context.model_dump(mode="json"),
            "normalized_query": None,
            "classification": {},
            "candidates": [],
            "candidate_contexts": [],
            "selection": {},
            "validation": {},
            "pending_tool_name": None,
            "collected_arguments": {},
            "missing_arguments": [],
            "ambiguous_arguments": [],
            "workflow_data": {},
            "profile_section_key": None,
            "profile_resource_key": None,
            "profile_field_keys": [],
            "profile_record_reference": None,
            "profile_record_id": None,
            "profile_write_mode": None,
            "profile_current_snapshot": {},
            "profile_changes": {},
            "missing_profile_slots": [],
            "entity_memory": {},
            "pending_action": {},
            "tool_result": None,
            "response_type": None,
            "capability_outcome": None,
            "response_text": None,
            "response_data": None,
            "workflow_issues": [],
            "current_step": 0,
            "stage_timings": {},
            "graph_events": [],
        }
        try:
            output = await self._graph.ainvoke(
                initial,
                config={
                    "configurable": {
                        "thread_id": trusted_context.conversation_id
                    },
                    "recursion_limit": (
                        self._context.settings.max_workflow_steps_per_request
                    ),
                },
                context=self._context,
            )
        except GraphRecursionError:
            return self._error_result(
                trusted_context,
                "WORKFLOW_STEP_LIMIT_EXCEEDED",
                started,
            )
        except (ConversationStateError, PendingActionError) as error:
            return self._error_result(trusted_context, error.code, started)
        except RuntimeError as error:
            code = str(error)
            if not code.isupper():
                code = "WORKFLOW_INTERNAL_ERROR"
            return self._error_result(trusted_context, code, started)
        timings = dict(output.get("stage_timings", {}))
        timings["total_ms"] = (perf_counter() - started) * 1000
        known = ChatStageTimings.model_fields
        return ChatPipelineResult(
            conversation_id=trusted_context.conversation_id,
            type=output.get("response_type") or ChatResponseType.ERROR,
            outcome=output.get("capability_outcome"),
            answer=output.get("response_text"),
            data=output.get("response_data"),
            timings=ChatStageTimings.model_validate(
                {key: value for key, value in timings.items() if key in known}
            ),
        )

    async def preview(self, message: str) -> dict[str, Any]:
        normalized = self._context.query_normalizer.normalize(message)
        classification = await self._context.query_classifier.classify(
            normalized
        )
        settings = self._context.settings
        from app.routing.schemas import CandidateRetrievalRequest

        retrieval = await self._context.candidate_retriever.retrieve(
            CandidateRetrievalRequest(
                query=normalized.normalized_text,
                classification=classification,
                top_k=settings.tool_top_k,
                fetch_k=settings.tool_fetch_k,
                min_score=settings.tool_min_score,
            )
        )
        contexts = self._context.tool_selector.build_candidate_contexts(
            retrieval.candidates
        )
        if not contexts:
            return {
                "classification": classification.model_dump(mode="json"),
                "candidates": [],
                "selection": None,
                "validation": None,
                "execution_skipped": True,
            }
        selection = await self._context.tool_selector.select(
            ToolSelectorRequest(
                original_query=message,
                normalized_query=normalized.normalized_text,
                classification=classification,
                candidates=contexts,
                current_date=datetime.now().date(),
                timezone="Asia/Ho_Chi_Minh",
            )
        )
        validation = None
        if selection.selected_tool:
            tool = self._context.tool_registry.get(selection.selected_tool)
            resolution = self._context.argument_resolver.resolve(
                selection,
                tool,
                query=normalized.normalized_text,
                current_date=datetime.now().date(),
                timezone="Asia/Ho_Chi_Minh",
            )
            validation = self._context.validator.validate(
                selection,
                resolution,
                classification=classification,
                candidates=contexts,
            )
        return {
            "classification": classification.model_dump(mode="json"),
            "candidates": [
                item.model_dump(mode="json")
                for item in retrieval.candidates
            ],
            "selection": selection.model_dump(mode="json"),
            "validation": (
                validation.model_dump(mode="json") if validation else None
            ),
            "execution_skipped": True,
        }

    @staticmethod
    def _error_result(
        trusted_context: TrustedExecutionContext,
        code: str,
        started: float,
    ) -> ChatPipelineResult:
        outcome = outcome_for_error(code)
        return ChatPipelineResult(
            conversation_id=trusted_context.conversation_id,
            type=ChatResponseType.ERROR,
            outcome=outcome,
            answer=public_outcome_message(outcome),
            data=None,
            timings=ChatStageTimings(
                total_ms=(perf_counter() - started) * 1000
            ),
        )
