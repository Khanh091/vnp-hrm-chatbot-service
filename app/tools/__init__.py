from app.tools.catalogs import ALL_TOOLS
from app.tools.definitions import ToolDefinition, ToolExecutionResult
from app.tools.registry import ToolRegistry


def build_tool_registry() -> ToolRegistry:
    """Build an isolated registry suitable for dependency injection and tests."""

    return ToolRegistry(ALL_TOOLS)


__all__ = [
    "ToolDefinition",
    "ToolExecutionResult",
    "ToolRegistry",
    "build_tool_registry",
]
