import json
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from app.llm.exceptions import LlmStructuredOutputError

SchemaT = TypeVar("SchemaT", bound=BaseModel)


StructuredOutputError = LlmStructuredOutputError


def parse_structured_output(
    content: str,
    schema: type[SchemaT],
) -> SchemaT:
    if not content.strip():
        raise StructuredOutputError("LLM returned empty content")
    try:
        payload = json.loads(content)
    except json.JSONDecodeError as error:
        raise StructuredOutputError("LLM returned invalid JSON") from error
    try:
        return schema.model_validate(payload)
    except ValidationError as error:
        raise StructuredOutputError(
            "LLM returned JSON that does not match the required schema"
        ) from error
