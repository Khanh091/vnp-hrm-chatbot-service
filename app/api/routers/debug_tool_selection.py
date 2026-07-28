from typing import Annotated, Any, cast

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field

from app.orchestration.pipeline import ChatPipeline

router = APIRouter(prefix="/debug/tool-selection", tags=["Debug"])


class DebugToolSelectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str = Field(min_length=1, max_length=4000)
    execute: bool = False


def get_chat_pipeline(request: Request) -> ChatPipeline:
    return cast(ChatPipeline, request.app.state.chat_pipeline)


PipelineDependency = Annotated[ChatPipeline, Depends(get_chat_pipeline)]


@router.post("")
async def debug_tool_selection(
    request: DebugToolSelectionRequest,
    pipeline: PipelineDependency,
) -> dict[str, Any]:
    # Execution is deliberately ignored: this endpoint never calls Odoo.
    return await pipeline.preview(request.message)
