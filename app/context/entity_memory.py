from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.context.entities import SubjectMention


class ReferencedEntity(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    entity_type: str
    entity_id: int | str
    label: str
    ordinal: int | None = None
    created_at: datetime
    attributes: dict[str, Any] = Field(default_factory=dict)


class ConversationEntityMemory(BaseModel):
    model_config = ConfigDict(extra="forbid")

    last_employees: list[ReferencedEntity] = Field(default_factory=list)
    last_departments: list[ReferencedEntity] = Field(default_factory=list)
    last_leave_requests: list[ReferencedEntity] = Field(default_factory=list)
    last_contracts: list[ReferencedEntity] = Field(default_factory=list)


class EntityMemoryService:
    def capture(
        self,
        *,
        tool_name: str,
        data: object,
        memory: ConversationEntityMemory,
    ) -> ConversationEntityMemory:
        if tool_name not in {
            "leave_get_history",
            "leave_get_request_status",
        }:
            return memory
        records = self._records(data)
        references: list[ReferencedEntity] = []
        now = datetime.now(timezone.utc)
        for ordinal, record in enumerate(records, start=1):
            entity_id = record.get("id") or record.get("request_id")
            if not isinstance(entity_id, (int, str)):
                continue
            code = record.get("code") or record.get("request_code")
            date_from = record.get("date_from")
            date_to = record.get("date_to")
            label_parts = [str(code or f"Đơn nghỉ #{entity_id}")]
            if date_from:
                label_parts.append(str(date_from))
                if date_to:
                    label_parts.append(f"đến {date_to}")
            references.append(
                ReferencedEntity(
                    entity_type="leave_request",
                    entity_id=entity_id,
                    label=" — ".join(label_parts),
                    ordinal=ordinal,
                    created_at=now,
                    attributes={
                        key: record[key]
                        for key in (
                            "code",
                            "request_code",
                            "date_from",
                            "date_to",
                            "state",
                        )
                        if key in record
                    },
                )
            )
        if not references:
            return memory
        return memory.model_copy(
            update={"last_leave_requests": references[:20]}
        )

    def resolve_leave_request(
        self,
        mention: SubjectMention,
        memory: ConversationEntityMemory,
    ) -> ReferencedEntity | None:
        items = memory.last_leave_requests
        if not items:
            return None
        index: int | None
        if mention.ordinal_reference is not None:
            index = mention.ordinal_reference - 1
        else:
            index = {
                "latest": 0,
                "first": 0,
                "previous": 1,
                "last": len(items) - 1,
            }.get(mention.recency_reference or "")
        if index is None or index < 0 or index >= len(items):
            return None
        return items[index]

    @staticmethod
    def _records(data: object) -> list[dict[str, Any]]:
        if isinstance(data, list):
            return [item for item in data if isinstance(item, dict)]
        if not isinstance(data, dict):
            return []
        for key in ("records", "items", "requests", "data", "result"):
            value = data.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
        if any(key in data for key in ("id", "request_id", "request_code")):
            return [data]
        return []
