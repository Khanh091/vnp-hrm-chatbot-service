import logging

from app.config import Settings
from app.llm.client import LlmClientError, StructuredOutputClient
from app.llm.prompts.tool_selector import (
    TOOL_SELECTOR_SYSTEM_PROMPT,
    build_tool_selector_prompt,
)
from app.llm.structured_output import StructuredOutputError
from app.routing.schemas import (
    Operation,
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
    "company_id",
    "conversation_id",
    "timezone",
}


class ToolSelectorError(RuntimeError):
    pass


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
        try:
            selection = await self._llm_client.complete_structured(
                system_prompt=TOOL_SELECTOR_SYSTEM_PROMPT,
                user_prompt=build_tool_selector_prompt(request),
                schema=ToolSelection,
            )
        except (LlmClientError, StructuredOutputError) as error:
            logger.warning(
                "tool_selection_failed reason_code=%s",
                type(error).__name__.upper(),
            )
            raise ToolSelectorError("Tool selection failed") from error

        if selection.selected_tool is not None:
            if selection.selected_tool not in allowed:
                raise ToolSelectorError("Selected tool is outside candidates")
            if _TRUSTED_FIELDS.intersection(selection.extracted_arguments):
                raise ToolSelectorError("LLM returned trusted context fields")
        return selection

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
            required = [
                name
                for name, field in tool.argument_schema.model_fields.items()
                if field.is_required() and name != "idempotency_key"
            ]
            optional = [
                name
                for name, field in tool.argument_schema.model_fields.items()
                if not field.is_required()
            ]
            contexts.append(
                ToolCandidateContext(
                    tool_name=tool.name,
                    domain=candidate.domain,
                    capability=tool.capability,
                    operation=Operation(tool.operation.value),
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
