from __future__ import annotations

import json
from typing import Any, cast

_BLOCKED_KEYS = {
    "request_id",
    "internal_id",
    "odoo_user_id",
    "employee_id",
    "company_id",
    "debug",
    "metadata",
    "endpoint",
    "tool_version",
    "idempotency_key",
    "authorization",
    "headers",
    "api_key",
    "access_token",
    "session_cookie",
    "attachment",
    "attachments",
    "binary",
    "file",
    "files",
    "file_content",
    "datas",
    "raw_data",
}


class ToolResultSanitizer:
    def __init__(self, *, max_items: int, max_chars: int) -> None:
        self._max_items = max_items
        self._max_chars = max_chars

    def sanitize(
        self,
        *,
        intent: object,
        tool_name: str,
        data: object,
    ) -> dict[str, object] | list[object] | None:
        del intent, tool_name
        sanitized, truncated = self._walk(data)
        if sanitized is None:
            return None
        if not isinstance(sanitized, (dict, list)):
            sanitized = {"value": sanitized}
        serialized = json.dumps(
            sanitized,
            ensure_ascii=False,
            default=str,
            separators=(",", ":"),
        )
        if len(serialized) > self._max_chars:
            return {
                "data_preview": serialized[: self._max_chars - 100],
                "truncated": True,
            }
        if truncated:
            if isinstance(sanitized, dict):
                sanitized = {**sanitized, "truncated": True}
            else:
                sanitized = [*sanitized, {"truncated": True}]
        return cast(dict[str, object] | list[object], sanitized)

    def _walk(self, value: object) -> tuple[Any, bool]:
        if isinstance(value, dict):
            dict_output: dict[str, Any] = {}
            truncated = False
            for raw_key, item in value.items():
                key = str(raw_key)
                if key.lower() in _BLOCKED_KEYS:
                    continue
                cleaned, child_truncated = self._walk(item)
                dict_output[key] = cleaned
                truncated = truncated or child_truncated
            return dict_output, truncated
        if isinstance(value, (list, tuple)):
            selected = value[: self._max_items]
            list_output: list[Any] = []
            truncated = len(value) > self._max_items
            for item in selected:
                cleaned, child_truncated = self._walk(item)
                list_output.append(cleaned)
                truncated = truncated or child_truncated
            return list_output, truncated
        if isinstance(value, (str, int, float, bool)) or value is None:
            return value, False
        return str(value), False
