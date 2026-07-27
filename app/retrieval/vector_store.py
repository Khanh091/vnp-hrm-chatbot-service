from typing import Protocol

from app.persistence.database import Database
from app.persistence.repositories.tool_embedding_repository import (
    SqlAlchemyToolEmbeddingRepository,
    VectorSearchMatch,
)


class VectorStore(Protocol):
    async def has_candidates(
        self,
        *,
        domains: tuple[str, ...],
        route_types: tuple[str, ...],
    ) -> bool: ...

    async def search(
        self,
        *,
        embedding: list[float],
        domains: tuple[str, ...],
        route_types: tuple[str, ...],
        limit: int,
    ) -> list[VectorSearchMatch]: ...


class PgVectorStore:
    def __init__(
        self,
        repository: SqlAlchemyToolEmbeddingRepository,
    ) -> None:
        self._repository = repository

    async def has_candidates(
        self,
        *,
        domains: tuple[str, ...],
        route_types: tuple[str, ...],
    ) -> bool:
        return await self._repository.has_candidates(
            domains=domains,
            route_types=route_types,
        )

    async def search(
        self,
        *,
        embedding: list[float],
        domains: tuple[str, ...],
        route_types: tuple[str, ...],
        limit: int,
    ) -> list[VectorSearchMatch]:
        return await self._repository.vector_search(
            embedding=embedding,
            domains=domains,
            route_types=route_types,
            limit=limit,
        )


class DatabasePgVectorStore:
    """Short-lived session adapter used by the debug routing pipeline."""

    def __init__(self, database: Database) -> None:
        self._database = database

    async def has_candidates(
        self,
        *,
        domains: tuple[str, ...],
        route_types: tuple[str, ...],
    ) -> bool:
        async with self._database.session() as session:
            return await SqlAlchemyToolEmbeddingRepository(
                session
            ).has_candidates(
                domains=domains,
                route_types=route_types,
            )

    async def search(
        self,
        *,
        embedding: list[float],
        domains: tuple[str, ...],
        route_types: tuple[str, ...],
        limit: int,
    ) -> list[VectorSearchMatch]:
        async with self._database.session() as session:
            return await SqlAlchemyToolEmbeddingRepository(
                session
            ).vector_search(
                embedding=embedding,
                domains=domains,
                route_types=route_types,
                limit=limit,
            )
