from __future__ import annotations

from hashlib import sha256

from pydantic import BaseModel, ConfigDict, Field

from app.persistence.repositories.tool_embedding_repository import (
    ToolEmbeddingRepository,
    ToolEmbeddingWrite,
)
from app.retrieval.embeddings import EmbeddingError, EmbeddingProvider
from app.tools.definitions import RouteType as ToolRouteType
from app.tools.definitions import ToolDefinition
from app.tools.registry import ToolRegistry


class ToolIndexSummary(BaseModel):
    model_config = ConfigDict(frozen=True)

    total_tools: int = Field(ge=0)
    inserted: int = Field(ge=0)
    updated: int = Field(ge=0)
    unchanged: int = Field(ge=0)
    disabled: int = Field(ge=0)
    failed: int = Field(ge=0)


def retrieval_route(tool: ToolDefinition) -> str:
    if tool.route_type is ToolRouteType.COMMAND:
        return "transaction"
    return "structured_query"


def build_tool_embedding_text(tool: ToolDefinition) -> str:
    positive = "\n".join(f"- {example}" for example in tool.examples)
    negative = "\n".join(
        f"- {example}" for example in tool.negative_examples
    )
    return "\n".join(
        (
            f"Tool: {tool.name}",
            f"Domain: {tool.domain.value}",
            f"Capability: {tool.capability}",
            f"Operation: {tool.operation.value}",
            f"Route: {retrieval_route(tool)}",
            f"Description: {tool.description}",
            "Positive examples:",
            positive,
            "Distinctions and negative examples:",
            negative,
        )
    )


def calculate_content_hash(embedding_text: str) -> str:
    return sha256(embedding_text.encode("utf-8")).hexdigest()


class ToolIndexer:
    def __init__(
        self,
        registry: ToolRegistry,
        repository: ToolEmbeddingRepository,
        embedding_provider: EmbeddingProvider,
    ) -> None:
        self._registry = registry
        self._repository = repository
        self._embedding_provider = embedding_provider

    async def sync_registry(self) -> ToolIndexSummary:
        tools = self._registry.list_all()
        keys = [(tool.name, tool.version) for tool in tools]
        if len(keys) != len(set(keys)):
            raise ValueError("duplicate tool name and version in registry")

        existing = {
            (record.tool_name, record.tool_version): record
            for record in await self._repository.list_records()
        }
        prepared = [
            (
                tool,
                build_tool_embedding_text(tool),
            )
            for tool in tools
        ]
        changed = [
            (tool, text)
            for tool, text in prepared
            if (record := existing.get((tool.name, tool.version))) is None
            or record.content_hash != calculate_content_hash(text)
        ]

        try:
            changed_embeddings = (
                await self._embedding_provider.embed_documents(
                    [text for _, text in changed]
                )
                if changed
                else []
            )
        except EmbeddingError:
            disabled = await self._repository.disable_missing(set(keys))
            return ToolIndexSummary(
                total_tools=len(tools),
                inserted=0,
                updated=0,
                unchanged=len(tools) - len(changed),
                disabled=disabled,
                failed=len(changed),
            )

        embedded = {
            (tool.name, tool.version): embedding
            for (tool, _), embedding in zip(
                changed,
                changed_embeddings,
                strict=True,
            )
        }
        inserted = 0
        updated = 0
        unchanged = 0
        for tool, text in prepared:
            key = (tool.name, tool.version)
            record = existing.get(key)
            content_hash = calculate_content_hash(text)
            embedding = embedded.get(key)

            if embedding is None and record is not None:
                if record.enabled == tool.enabled:
                    unchanged += 1
                    continue
                embedding = record.embedding

            if embedding is None:
                raise RuntimeError("missing embedding for changed tool")

            await self._repository.upsert(
                ToolEmbeddingWrite(
                    tool_name=tool.name,
                    tool_version=tool.version,
                    domain=tool.domain.value,
                    route_type=retrieval_route(tool),
                    capability=tool.capability,
                    operation=tool.operation.value,
                    embedding_text=text,
                    embedding=embedding,
                    content_hash=content_hash,
                    enabled=tool.enabled,
                )
            )
            if record is None:
                inserted += 1
            else:
                updated += 1

        disabled = await self._repository.disable_missing(set(keys))
        return ToolIndexSummary(
            total_tools=len(tools),
            inserted=inserted,
            updated=updated,
            unchanged=unchanged,
            disabled=disabled,
            failed=0,
        )
