import logging

from app.config import Settings
from app.llm.client import LlmClientError, StructuredOutputClient
from app.llm.prompts.tool_selector import (
    TOOL_SELECTOR_SYSTEM_PROMPT,
    build_tool_selector_prompt,
)
from app.llm.structured_output import StructuredOutputError
from app.routing.schemas import (
    RouteType,
    SubjectScope,
    ToolCandidate,
    ToolCandidateContext,
    ToolSelection,
    ToolSelectorRequest,
)
from app.tools.definitions import RouteType as ToolRouteType
from app.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)
_TRUSTED_FIELDS = {
    "odoo_user_id",
    "employee_id",
    "department_id",
    "company_id",
    "contract_type_id",
    "company_ids",
    "group_codes",
    "capabilities",
    "conversation_id",
    "timezone",
}


class ToolSelectorError(RuntimeError):
    def __init__(self, message: str, *, reason_code: str) -> None:
        super().__init__(message)
        self.reason_code = reason_code


class ToolSelector:
    def __init__(
        self,
        llm_client: StructuredOutputClient,
        registry: ToolRegistry,
        settings: Settings | None = None,
    ) -> None:
        self._llm_client = llm_client
        self._registry = registry
        self._max_candidates = (
            settings.tool_selector_max_candidates if settings else None
        )
        self._examples_per_kind = (
            settings.tool_selector_examples_per_kind if settings else None
        )

    async def select(self, request: ToolSelectorRequest) -> ToolSelection:
        allowed = {candidate.tool_name for candidate in request.candidates}
        if not allowed:
            return ToolSelection(
                selected_tool=None,
                confidence=1.0,
                reason_code="NO_CANDIDATE_TOOL",
            )
        if len(request.candidates) == 1:
            candidate = request.candidates[0]
            tool = self._registry.get(candidate.tool_name)
            if (
                request.classification.intent is not None
                and tool.supports_intent(request.classification.intent)
                and tool.query_operation is request.classification.operation
            ):
                return ToolSelection(
                    selected_tool=tool.name,
                    confidence=request.classification.confidence,
                    scope=request.classification.scope,
                    reason_code="DIRECT_INTENT_MAPPING",
                )
        try:
            selection = await self._llm_client.complete_structured(
                system_prompt=TOOL_SELECTOR_SYSTEM_PROMPT,
                user_prompt=build_tool_selector_prompt(request),
                schema=ToolSelection,
                operation="tool_selection",
            )
        except (LlmClientError, StructuredOutputError) as error:
            reason_code = (
                "SELECTOR_INVALID_OUTPUT"
                if isinstance(error, StructuredOutputError)
                else "SELECTOR_PROVIDER_ERROR"
            )
            logger.warning(
                "tool_selection_failed reason_code=%s",
                reason_code,
            )
            raise ToolSelectorError(
                "Tool selection failed",
                reason_code=reason_code,
            ) from error

        if selection.selected_tool is not None:
            if selection.selected_tool not in allowed:
                raise ToolSelectorError(
                    "Selected tool is outside candidates",
                    reason_code="SELECTOR_TOOL_NOT_IN_CANDIDATES",
                )
            if _TRUSTED_FIELDS.intersection(selection.extracted_arguments):
                raise ToolSelectorError(
                    "LLM returned trusted context fields",
                    reason_code="SELECTOR_TRUSTED_FIELD_INJECTION",
                )
        return selection.model_copy(
            update={"scope": request.classification.scope}
        )

    def build_candidate_contexts(
        self,
        candidates: list[ToolCandidate],
    ) -> list[ToolCandidateContext]:
        contexts: list[ToolCandidateContext] = []
        selected_candidates = (
            candidates[: self._max_candidates]
            if self._max_candidates is not None
            else candidates
        )
        for candidate in selected_candidates:
            tool = self._registry.get(candidate.tool_name)
            required = list(tool.required_arguments)
            optional = list(tool.optional_arguments)
            contexts.append(
                ToolCandidateContext(
                    tool_name=tool.name,
                    domain=candidate.domain,
                    capability=tool.capability,
                    supported_intents=sorted(
                        tool.intents,
                        key=lambda intent: intent.value,
                    ),
                    operation=tool.query_operation,
                    route_type=(
                        RouteType.TRANSACTION
                        if tool.route_type is ToolRouteType.COMMAND
                        else RouteType.STRUCTURED_QUERY
                    ),
                    risk_level=tool.risk_level,
                    description=tool.description,
                    required_arguments=required,
                    optional_arguments=optional,
                    examples=list(
                        tool.examples[: self._examples_per_kind]
                        if self._examples_per_kind is not None
                        else tool.examples
                    ),
                    negative_examples=list(
                        tool.negative_examples[: self._examples_per_kind]
                        if self._examples_per_kind is not None
                        else tool.negative_examples
                    ),
                    supported_scopes=[
                        SubjectScope(scope.value)
                        for scope in tool.supported_scopes
                    ],
                    requires_confirmation=tool.requires_confirmation,
                    score=candidate.score,
                )
            )
        return contexts
