from dataclasses import dataclass

from app.config import Settings
from app.context.conversation_service import ConversationService
from app.context.date_resolver import DateResolver
from app.context.dialog_manager import DialogTurnManager
from app.context.entity_resolver import BusinessEntityResolver, EntityResolver
from app.context.pending_action_service import PendingActionService
from app.routing.argument_resolver import ArgumentResolver
from app.routing.candidate_retriever import CandidateRetriever
from app.routing.query_classifier import QueryClassifier
from app.routing.query_normalizer import QueryNormalizer
from app.routing.tool_selector import ToolSelector
from app.routing.validator import ToolSelectionValidator
from app.security.authorization import AuthorizationPolicyService
from app.tools.executor import ToolExecutor
from app.tools.registry import ToolRegistry
from app.tools.response_formatter import ToolResponseFormatter
from app.workflows.registry import WorkflowRegistry
from app.workflows.slot_manager import SlotManager


@dataclass(frozen=True)
class GraphContext:
    query_normalizer: QueryNormalizer
    query_classifier: QueryClassifier
    candidate_retriever: CandidateRetriever
    tool_selector: ToolSelector
    argument_resolver: ArgumentResolver
    date_resolver: DateResolver
    dialog_turn_manager: DialogTurnManager
    entity_resolver: EntityResolver
    business_entity_resolver: BusinessEntityResolver
    validator: ToolSelectionValidator
    authorization_policy: AuthorizationPolicyService
    tool_executor: ToolExecutor
    response_formatter: ToolResponseFormatter
    conversation_service: ConversationService
    pending_action_service: PendingActionService
    workflow_registry: WorkflowRegistry
    slot_manager: SlotManager
    tool_registry: ToolRegistry
    settings: Settings
