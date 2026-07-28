from dataclasses import dataclass


@dataclass(frozen=True)
class WorkflowDefinition:
    tool_name: str
    clarification_priority: tuple[str, ...]
    confirmation_title: str
    confirmation_question: str

    def next_field(
        self, missing: list[str], ambiguous: list[str]
    ) -> str | None:
        unresolved = set(ambiguous) | set(missing)
        return next(
            (field for field in self.clarification_priority if field in unresolved),
            next(iter(unresolved), None),
        )
