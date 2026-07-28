from dataclasses import dataclass

from app.config import Settings
from app.context.conversation_service import ConversationService
from app.context.date_resolver import DateResolver
from app.context.entity_resolver import EntityResolver
from app.context.pending_action_service import PendingActionService
from app.routing.argument_resolver import ArgumentResolver
from app.routing.candidate_retriever import CandidateRetriever
from app.routing.query_classifier import QueryClassifier
from app.routing.query_normalizer import QueryNormalizer
from app.routing.tool_selector import ToolSelector
from app.routing.validator import ToolSelectionValidator
from app.tools.executor import ToolExecutor
from app.tools.registry import ToolRegistry
from app.tools.response_formatter import ToolResponseFormatter
from app.workflows.registry import WorkflowRegistry


@dataclass(frozen=True)
class GraphContext:
    query_normalizer: QueryNormalizer
    query_classifier: QueryClassifier
    candidate_retriever: CandidateRetriever
    tool_selector: ToolSelector
    argument_resolver: ArgumentResolver
    date_resolver: DateResolver
    entity_resolver: EntityResolver
    validator: ToolSelectionValidator
    tool_executor: ToolExecutor
    response_formatter: ToolResponseFormatter
    conversation_service: ConversationService
    pending_action_service: PendingActionService
    workflow_registry: WorkflowRegistry
    tool_registry: ToolRegistry
    settings: Settings
