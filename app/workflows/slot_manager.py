from __future__ import annotations

from datetime import date
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.context.entities import EntityAmbiguity
from app.workflows.definitions import WorkflowDefinition


class SlotIssue(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    code: str
    field: str | None = None


class SlotState(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    values: dict[str, Any] = Field(default_factory=dict)
    missing: list[str] = Field(default_factory=list)
    ambiguous: list[str] = Field(default_factory=list)
    issues: list[SlotIssue] = Field(default_factory=list)


class SlotManager:
    def initialize(
        self,
        workflow: WorkflowDefinition,
        values: dict[str, Any] | None = None,
    ) -> SlotState:
        return self.validate(workflow, values or {})

    def merge(
        self,
        workflow: WorkflowDefinition,
        current: SlotState,
        values: dict[str, Any],
        ambiguities: list[EntityAmbiguity] | None = None,
    ) -> SlotState:
        allowed = {slot.name for slot in workflow.slots}
        merged = dict(current.values)
        merged.update(
            {name: value for name, value in values.items() if name in allowed}
        )
        state = self.validate(workflow, merged)
        ambiguous = [
            item.field
            for item in ambiguities or []
            if item.field in allowed
        ]
        return state.model_copy(
            update={
                "ambiguous": list(
                    dict.fromkeys(
                        [*current.ambiguous, *state.ambiguous, *ambiguous]
                    )
                )
            }
        )

    def validate(
        self,
        workflow: WorkflowDefinition,
        values: dict[str, Any],
    ) -> SlotState:
        allowed = {slot.name for slot in workflow.slots}
        normalized = {
            name: value
            for name, value in values.items()
            if name in allowed or name == "idempotency_key"
        }
        missing = [
            slot.name
            for slot in sorted(workflow.slots, key=lambda item: item.priority)
            if slot.required and normalized.get(slot.name) is None
        ]
        issues: list[SlotIssue] = []
        value_from = self._as_date(normalized.get("date_from"))
        value_to = self._as_date(normalized.get("date_to"))
        if value_from and value_to and value_from > value_to:
            issues.append(
                SlotIssue(
                    code="INVALID_DATE_RANGE",
                    field="date_to",
                )
            )
        for name in ("leave_type_id", "request_id"):
            value = normalized.get(name)
            if value is not None and (
                isinstance(value, bool)
                or not isinstance(value, int)
                or value <= 0
            ):
                issues.append(
                    SlotIssue(code="INVALID_SLOT_VALUE", field=name)
                )
        return SlotState(
            values=normalized,
            missing=missing,
            issues=issues,
        )

    def get_missing_slots(
        self,
        workflow: WorkflowDefinition,
        state: SlotState,
    ) -> list[str]:
        priorities = {slot.name: slot.priority for slot in workflow.slots}
        return sorted(state.missing, key=lambda name: priorities.get(name, 999))

    def get_next_slot(
        self,
        workflow: WorkflowDefinition,
        state: SlotState,
    ) -> str | None:
        unresolved = set(state.ambiguous) | set(state.missing)
        return next(
            (
                slot.name
                for slot in sorted(
                    workflow.slots,
                    key=lambda item: item.priority,
                )
                if slot.name in unresolved
            ),
            None,
        )

    @staticmethod
    def clear() -> SlotState:
        return SlotState()

    @staticmethod
    def _as_date(value: Any) -> date | None:
        if isinstance(value, date):
            return value
        if isinstance(value, str):
            try:
                return date.fromisoformat(value)
            except ValueError:
                return None
        return None
