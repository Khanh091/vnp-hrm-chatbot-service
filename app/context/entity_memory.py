from __future__ import annotations

from datetime import date, datetime, timezone
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
        records = sorted(
            self._records(data),
            key=self._leave_sort_key,
            reverse=True,
        )
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
                label_parts.append(self._display_date(date_from))
                if date_to:
                    label_parts.append(f"đến {self._display_date(date_to)}")
            state_label = self._state_label(record.get("state"))
            if state_label:
                label_parts.append(state_label)
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
        if mention.date_reference is not None:
            expected = self._parse_reference_date(str(mention.date_reference))
            matches = [
                item
                for item in items
                if self._matches_reference_date(item, expected)
            ]
            return matches[0] if len(matches) == 1 else None
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
    def _leave_sort_key(record: dict[str, Any]) -> tuple[str, str]:
        return (
            str(record.get("date_from") or record.get("date_to") or ""),
            str(record.get("id") or record.get("request_id") or ""),
        )

    @staticmethod
    def _display_date(value: object) -> str:
        try:
            parsed = date.fromisoformat(str(value)[:10])
        except ValueError:
            return str(value)
        return parsed.strftime("%d/%m/%Y")

    @staticmethod
    def _state_label(value: object) -> str | None:
        return {
            "draft": "Nháp",
            "wait_approve": "Chờ duyệt",
            "confirm": "Đã xác nhận",
            "approve": "Đã duyệt",
            "reject": "Đã từ chối",
            "cancel": "Đã hủy",
        }.get(str(value or "").casefold())

    @staticmethod
    def _parse_reference_date(
        value: str,
    ) -> tuple[int, int, int | None] | None:
        parts = value.replace("-", "/").split("/")
        if len(parts) not in {2, 3}:
            return None
        try:
            return (
                int(parts[0]),
                int(parts[1]),
                int(parts[2]) if len(parts) == 3 else None,
            )
        except ValueError:
            return None

    @staticmethod
    def _matches_reference_date(
        item: ReferencedEntity,
        expected: tuple[int, int, int | None] | None,
    ) -> bool:
        if expected is None:
            return False
        day, month, year = expected
        for field in ("date_from", "date_to"):
            raw = item.attributes.get(field)
            try:
                parsed = date.fromisoformat(str(raw)[:10])
            except ValueError:
                continue
            if (
                parsed.day == day
                and parsed.month == month
                and (year is None or parsed.year == year)
            ):
                return True
        return False

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
