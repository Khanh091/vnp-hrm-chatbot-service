from __future__ import annotations

from app.tools.registry import ToolRegistry


def build_tool_registry() -> ToolRegistry:
    """Build an isolated registry without importing catalogs at package load."""

    from app.tools.catalogs import ALL_TOOLS

    return ToolRegistry(ALL_TOOLS)


__all__ = ["ToolRegistry", "build_tool_registry"]
