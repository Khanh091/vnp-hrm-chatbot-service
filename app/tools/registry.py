from collections.abc import Iterable

from app.routing.intent_tool_mapping import tool_names_for_intent
from app.routing.taxonomy import (
    Intent,
    QueryRoute,
    SubjectType,
)
from app.routing.taxonomy import (
    Operation as QueryOperation,
)
from app.routing.taxonomy import (
    SubjectScope as QuerySubjectScope,
)
from app.tools.definitions import Domain, RouteType, ToolDefinition
from app.tools.policies import validate_tool_definition


class ToolRegistryError(ValueError):
    pass


class DuplicateToolError(ToolRegistryError):
    pass


class ToolNotFoundError(ToolRegistryError):
    pass


class ToolRegistry:
    def __init__(self, tools: Iterable[ToolDefinition] = ()) -> None:
        self._tools: dict[str, ToolDefinition] = {}
        for tool in tools:
            self.register(tool)

    def register(self, tool: ToolDefinition) -> None:
        validate_tool_definition(tool)
        if tool.name in self._tools:
            raise DuplicateToolError(f"tool already registered: {tool.name}")
        self._tools[tool.name] = tool

    def get(self, name: str) -> ToolDefinition:
        try:
            return self._tools[name]
        except KeyError as error:
            raise ToolNotFoundError(f"tool not registered: {name}") from error

    def list_all(self) -> tuple[ToolDefinition, ...]:
        return tuple(self._tools.values())

    def list_by_domain(self, domain: Domain) -> tuple[ToolDefinition, ...]:
        return self.filter(domain=domain)

    def filter(
        self,
        *,
        domain: Domain | None = None,
        route_type: RouteType | None = None,
        enabled: bool | None = None,
    ) -> tuple[ToolDefinition, ...]:
        return tuple(
            tool
            for tool in self._tools.values()
            if (domain is None or tool.domain is domain)
            and (route_type is None or tool.route_type is route_type)
            and (enabled is None or tool.enabled is enabled)
        )

    def find_tools(
        self,
        *,
        intent: Intent | None = None,
        domain: str | None = None,
        route: QueryRoute | None = None,
        operation: QueryOperation | None = None,
        scope: QuerySubjectScope | None = None,
        enabled: bool = True,
    ) -> tuple[ToolDefinition, ...]:
        """Return the deterministic runtime allowlist before vector retrieval."""
        intent_tools = (
            frozenset(tool_names_for_intent(intent))
            if intent is not None
            else None
        )
        return tuple(
            tool
            for tool in self._tools.values()
            if (intent_tools is None or tool.name in intent_tools)
            and (domain is None or tool.domain.value == domain)
            and (route is None or tool.route is route)
            and (operation is None or tool.query_operation is operation)
            and (
                scope is None
                or {
                    QuerySubjectScope.SELF: SubjectType.SELF,
                    QuerySubjectScope.NAMED_EMPLOYEE: SubjectType.EMPLOYEE,
                    QuerySubjectScope.DEPARTMENT: SubjectType.DEPARTMENT,
                    QuerySubjectScope.COMPANY: SubjectType.COMPANY,
                    QuerySubjectScope.GENERAL: SubjectType.GENERAL,
                    QuerySubjectScope.UNKNOWN: SubjectType.GENERAL,
                    QuerySubjectScope.DIRECT_REPORTS: SubjectType.EMPLOYEE,
                }[scope]
                in tool.supported_subject_types
            )
            and (not enabled or tool.enabled)
        )
