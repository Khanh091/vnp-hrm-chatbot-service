from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from app.routing.taxonomy import Intent, Operation, QueryRoute


class FinalAnswerContext(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    original_query: str
    route: QueryRoute
    intent: Intent
    operation: Operation
    tool_name: str
    data: dict[str, object] | list[object] | None
    locale: str
    timezone: str
