from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.routing.taxonomy import Intent


class SlotDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(min_length=1, max_length=100)
    entity_type: str = Field(min_length=1, max_length=100)
    required: bool
    priority: int = Field(ge=1)
    prompt: str = Field(min_length=1, max_length=500)
    allows_structured_option: bool = False
    validator_name: str | None = Field(default=None, max_length=100)


class WorkflowDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    intent: Intent
    tool_name: str = Field(min_length=1, max_length=100)
    slots: tuple[SlotDefinition, ...]
    requires_confirmation: bool
    confirmation_title: str = Field(min_length=1, max_length=300)
    confirmation_question: str = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def unique_slots_and_priorities(self) -> WorkflowDefinition:
        names = [slot.name for slot in self.slots]
        if len(names) != len(set(names)):
            raise ValueError("workflow slot names must be unique")
        priorities = [slot.priority for slot in self.slots]
        if len(priorities) != len(set(priorities)):
            raise ValueError("workflow slot priorities must be unique")
        return self

    @property
    def clarification_priority(self) -> tuple[str, ...]:
        return tuple(
            slot.name
            for slot in sorted(self.slots, key=lambda item: item.priority)
        )

    def next_field(
        self,
        missing: list[str],
        ambiguous: list[str],
    ) -> str | None:
        unresolved = set(ambiguous) | set(missing)
        return next(
            (
                field
                for field in self.clarification_priority
                if field in unresolved
            ),
            None,
        )

    def slot(self, name: str) -> SlotDefinition | None:
        return next((slot for slot in self.slots if slot.name == name), None)
