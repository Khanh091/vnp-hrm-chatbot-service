from __future__ import annotations

from app.routing.capabilities import (
    CapabilityResolver,
    RoutingResolutionError,
    ToolResolver,
)
from app.routing.taxonomy import Intent, SubjectType
from app.tools import build_tool_registry


def tool_names_for_intent(
    intent: Intent | None,
    *,
    subject_type: SubjectType = SubjectType.SELF,
) -> tuple[str, ...]:
    """Compatibility facade backed by Intent → Capability → Tool resolution."""

    registry = build_tool_registry()
    try:
        capabilities = CapabilityResolver().resolve(
            intent=intent,
            subject_type=subject_type,
        )
        tools = [
            tool
            for capability in capabilities
            for tool in ToolResolver(registry).resolve(
                capability=capability,
                subject_type=subject_type,
            )
            if intent is not None and tool.supports_intent(intent)
        ]
    except RoutingResolutionError:
        return ()
    return tuple(dict.fromkeys(tool.name for tool in tools))


def tool_supports_intent(
    tool_name: str,
    intent: Intent,
    *,
    subject_type: SubjectType = SubjectType.SELF,
) -> bool:
    return tool_name in tool_names_for_intent(
        intent,
        subject_type=subject_type,
    )


__all__ = ["tool_names_for_intent", "tool_supports_intent"]
