import re

from pydantic import BaseModel

from app.tools.definitions import (
    RiskLevel,
    RouteType,
    ToolArguments,
    ToolDefinition,
)

TOOL_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]{2,63}$")
ENDPOINT_PATTERN = re.compile(
    r"^/api/hrm-chatbot/v1/[a-z0-9/-]+(?:\{[a-z_]+\}[a-z0-9/-]*)?$"
)
PLACEHOLDER_PATTERN = re.compile(r"\{([a-z_]+)\}")


class ToolPolicyError(ValueError):
    pass


def validate_tool_definition(tool: ToolDefinition) -> None:
    if not TOOL_NAME_PATTERN.fullmatch(tool.name):
        raise ToolPolicyError("tool name must be a stable snake_case identifier")
    if not tool.capability.strip() or not tool.description.strip():
        raise ToolPolicyError("capability and description are required")
    if not ENDPOINT_PATTERN.fullmatch(tool.endpoint):
        raise ToolPolicyError("endpoint must be a local HRM chatbot API path")
    if "?" in tool.endpoint or "://" in tool.endpoint or ".." in tool.endpoint:
        raise ToolPolicyError("endpoint must not contain a URL, query, or traversal")
    if not issubclass(tool.argument_schema, ToolArguments):
        raise ToolPolicyError("argument_schema must inherit ToolArguments")
    if tool.response_schema is not None and not issubclass(
        tool.response_schema, BaseModel
    ):
        raise ToolPolicyError("response_schema must be a Pydantic model")

    placeholders = tuple(PLACEHOLDER_PATTERN.findall(tool.endpoint))
    if placeholders != tool.path_arguments:
        raise ToolPolicyError("path_arguments must exactly match endpoint placeholders")
    schema_fields = tool.argument_schema.model_fields
    if any(name not in schema_fields for name in tool.path_arguments):
        raise ToolPolicyError("path argument is missing from argument schema")

    if len(tool.examples) < 5 or len(tool.negative_examples) < 3:
        raise ToolPolicyError("each tool needs at least 5 examples and 3 negatives")
    if len(set(tool.examples)) != len(tool.examples):
        raise ToolPolicyError("positive examples must be unique")
    if len(set(tool.negative_examples)) != len(tool.negative_examples):
        raise ToolPolicyError("negative examples must be unique")
    if not tool.supported_scopes:
        raise ToolPolicyError("at least one subject scope is required")

    is_write = tool.risk_level in {
        RiskLevel.WRITE,
        RiskLevel.HIGH_RISK_WRITE,
    }
    if tool.route_type is RouteType.COMMAND and not is_write:
        raise ToolPolicyError("command tools must have a write risk level")
    if is_write and not tool.requires_confirmation:
        raise ToolPolicyError("write tools must require confirmation")
