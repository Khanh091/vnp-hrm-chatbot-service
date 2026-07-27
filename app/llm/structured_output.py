from typing import TypeVar

from pydantic import BaseModel, ValidationError

SchemaT = TypeVar("SchemaT", bound=BaseModel)


class StructuredOutputError(ValueError):
    pass


def parse_structured_output(
    content: str,
    schema: type[SchemaT],
) -> SchemaT:
    try:
        return schema.model_validate_json(content)
    except ValidationError as error:
        raise StructuredOutputError(
            "LLM returned output that does not match the required schema"
        ) from error
