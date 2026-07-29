from collections.abc import Mapping
from typing import Any, cast

from pydantic_core import to_jsonable_python


def json_safe_dict(value: Mapping[str, Any]) -> dict[str, Any]:
    """Convert workflow payloads to values accepted by PostgreSQL JSONB."""

    converted = to_jsonable_python(dict(value))
    if not isinstance(converted, dict):
        raise TypeError("expected a JSON object")
    return cast(dict[str, Any], converted)
