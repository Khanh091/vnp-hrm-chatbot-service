from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.persistence.models.tool_embedding import ToolEmbedding


@dataclass(frozen=True)
class ToolEmbeddingRecord:
    tool_name: str
    tool_version: str
    content_hash: str
    enabled: bool
    embedding: list[float]


@dataclass(frozen=True)
class ToolEmbeddingWrite:
    tool_name: str
    tool_version: str
    domain: str
    route_type: str
    capability: str
    operation: str
    embedding_text: str
    embedding: list[float]
    content_hash: str
    enabled: bool


@dataclass(frozen=True)
class VectorSearchMatch:
    tool_name: str
    domain: str
    capability: str
    operation: str
    score: float


class ToolEmbeddingRepository(Protocol):
    async def list_records(self) -> list[ToolEmbeddingRecord]: ...

    async def upsert(self, value: ToolEmbeddingWrite) -> None: ...

    async def disable_missing(
        self,
        active_keys: set[tuple[str, str]],
    ) -> int: ...


class SqlAlchemyToolEmbeddingRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_records(self) -> list[ToolEmbeddingRecord]:
        rows = (
            await self._session.execute(
                select(
                    ToolEmbedding.tool_name,
                    ToolEmbedding.tool_version,
                    ToolEmbedding.content_hash,
                    ToolEmbedding.enabled,
                    ToolEmbedding.embedding,
                )
            )
        ).all()
        return [
            ToolEmbeddingRecord(
                tool_name=row.tool_name,
                tool_version=row.tool_version,
                content_hash=row.content_hash,
                enabled=row.enabled,
                embedding=list(row.embedding),
            )
            for row in rows
        ]

    async def upsert(self, value: ToolEmbeddingWrite) -> None:
        statement = insert(ToolEmbedding).values(
            tool_name=value.tool_name,
            tool_version=value.tool_version,
            domain=value.domain,
            route_type=value.route_type,
            capability=value.capability,
            operation=value.operation,
            embedding_text=value.embedding_text,
            embedding=value.embedding,
            content_hash=value.content_hash,
            enabled=value.enabled,
        )
        statement = statement.on_conflict_do_update(
            constraint="uq_tool_embedding_name_version",
            set_={
                "domain": statement.excluded.domain,
                "route_type": statement.excluded.route_type,
                "capability": statement.excluded.capability,
                "operation": statement.excluded.operation,
                "embedding_text": statement.excluded.embedding_text,
                "embedding": statement.excluded.embedding,
                "content_hash": statement.excluded.content_hash,
                "enabled": statement.excluded.enabled,
                "updated_at": func.now(),
            },
        )
        await self._session.execute(statement)

    async def disable_missing(
        self,
        active_keys: set[tuple[str, str]],
    ) -> int:
        rows = (
            await self._session.execute(
                select(
                    ToolEmbedding.id,
                    ToolEmbedding.tool_name,
                    ToolEmbedding.tool_version,
                ).where(ToolEmbedding.enabled.is_(True))
            )
        ).all()
        ids = [
            row.id
            for row in rows
            if (row.tool_name, row.tool_version) not in active_keys
        ]
        if not ids:
            return 0
        await self._session.execute(
            update(ToolEmbedding)
            .where(ToolEmbedding.id.in_(ids))
            .values(enabled=False, updated_at=func.now())
        )
        return len(ids)

    async def has_candidates(
        self,
        *,
        domains: tuple[str, ...],
        route_types: tuple[str, ...],
        operations: tuple[str, ...],
    ) -> bool:
        count = await self._session.scalar(
            select(func.count())
            .select_from(ToolEmbedding)
            .where(
                ToolEmbedding.enabled.is_(True),
                ToolEmbedding.domain.in_(domains),
                ToolEmbedding.route_type.in_(route_types),
                ToolEmbedding.operation.in_(operations),
            )
        )
        return bool(count)

    async def vector_search(
        self,
        *,
        embedding: list[float],
        domains: tuple[str, ...],
        route_types: tuple[str, ...],
        operations: tuple[str, ...],
        limit: int,
    ) -> list[VectorSearchMatch]:
        cosine_distance = ToolEmbedding.embedding.cosine_distance(embedding)
        score = (1 - cosine_distance).label("score")
        rows = (
            await self._session.execute(
                select(
                    ToolEmbedding.tool_name,
                    ToolEmbedding.domain,
                    ToolEmbedding.capability,
                    ToolEmbedding.operation,
                    score,
                )
                .where(
                    ToolEmbedding.enabled.is_(True),
                    ToolEmbedding.domain.in_(domains),
                    ToolEmbedding.route_type.in_(route_types),
                    ToolEmbedding.operation.in_(operations),
                )
                .order_by(cosine_distance)
                .limit(limit)
            )
        ).all()
        return [
            VectorSearchMatch(
                tool_name=row.tool_name,
                domain=row.domain,
                capability=row.capability,
                operation=row.operation,
                score=float(row.score),
            )
            for row in rows
        ]
