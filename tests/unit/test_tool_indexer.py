from typing import Any

import pytest

from app.persistence.repositories.tool_embedding_repository import (
    ToolEmbeddingRecord,
    ToolEmbeddingWrite,
)
from app.retrieval.embeddings import EmbeddingError
from app.retrieval.tool_indexer import (
    ToolIndexer,
    build_tool_embedding_text,
    calculate_content_hash,
)
from app.tools import build_tool_registry
from app.tools.registry import ToolRegistry


class FakeRepository:
    def __init__(
        self,
        records: list[ToolEmbeddingRecord] | None = None,
    ) -> None:
        self.records = records or []
        self.writes: list[ToolEmbeddingWrite] = []
        self.disabled_keys: set[tuple[str, str]] = set()

    async def list_records(self) -> list[ToolEmbeddingRecord]:
        return self.records

    async def upsert(self, value: ToolEmbeddingWrite) -> None:
        self.writes.append(value)

    async def disable_missing(
        self,
        active_keys: set[tuple[str, str]],
    ) -> int:
        self.disabled_keys = {
            (record.tool_name, record.tool_version)
            for record in self.records
            if record.enabled
            and (record.tool_name, record.tool_version) not in active_keys
        }
        return len(self.disabled_keys)


class FakeEmbeddings:
    dimension = 2

    def __init__(self, error: bool = False) -> None:
        self.error = error
        self.calls: list[list[str]] = []

    async def embed_query(self, text: str) -> list[float]:
        return [0.1, 0.2]

    async def embed_documents(
        self,
        texts: list[str],
    ) -> list[list[float]]:
        self.calls.append(texts)
        if self.error:
            raise EmbeddingError("failed")
        return [[float(index), 0.2] for index, _ in enumerate(texts)]


def one_tool_registry() -> ToolRegistry:
    return ToolRegistry([build_tool_registry().get("leave_get_balance")])


def existing_record(
    *,
    content_hash: str,
    enabled: bool = True,
    tool_name: str = "leave_get_balance",
) -> ToolEmbeddingRecord:
    return ToolEmbeddingRecord(
        tool_name=tool_name,
        tool_version="1.0",
        content_hash=content_hash,
        enabled=enabled,
        embedding=[0.1, 0.2],
    )


@pytest.mark.asyncio
async def test_indexer_inserts_new_tool_in_one_batch() -> None:
    repository = FakeRepository()
    embeddings = FakeEmbeddings()

    summary = await ToolIndexer(
        one_tool_registry(), repository, embeddings
    ).sync_registry()

    assert summary.inserted == 1
    assert len(repository.writes) == 1
    assert len(embeddings.calls) == 1


@pytest.mark.asyncio
async def test_indexer_does_not_embed_unchanged_tool() -> None:
    tool = one_tool_registry().list_all()[0]
    record = existing_record(
        content_hash=calculate_content_hash(build_tool_embedding_text(tool))
    )
    repository = FakeRepository([record])
    embeddings = FakeEmbeddings()

    summary = await ToolIndexer(
        ToolRegistry([tool]), repository, embeddings
    ).sync_registry()

    assert summary.unchanged == 1
    assert embeddings.calls == []
    assert repository.writes == []


@pytest.mark.asyncio
async def test_indexer_reembeds_changed_metadata() -> None:
    tool = one_tool_registry().list_all()[0].model_copy(
        update={"description": "Mô tả metadata mới cho số dư phép."}
    )
    repository = FakeRepository([existing_record(content_hash="old")])

    summary = await ToolIndexer(
        ToolRegistry([tool]), repository, FakeEmbeddings()
    ).sync_registry()

    assert summary.updated == 1
    assert repository.writes[0].content_hash != "old"


@pytest.mark.asyncio
async def test_indexer_updates_disabled_state_without_reembedding() -> None:
    tool = one_tool_registry().list_all()[0].model_copy(
        update={"enabled": False}
    )
    content_hash = calculate_content_hash(build_tool_embedding_text(tool))
    repository = FakeRepository(
        [existing_record(content_hash=content_hash, enabled=True)]
    )
    embeddings = FakeEmbeddings()

    summary = await ToolIndexer(
        ToolRegistry([tool]), repository, embeddings
    ).sync_registry()

    assert summary.updated == 1
    assert repository.writes[0].enabled is False
    assert embeddings.calls == []


@pytest.mark.asyncio
async def test_indexer_disables_tool_removed_from_registry() -> None:
    repository = FakeRepository(
        [existing_record(content_hash="hash", tool_name="removed_tool")]
    )

    summary = await ToolIndexer(
        ToolRegistry(), repository, FakeEmbeddings()
    ).sync_registry()

    assert summary.disabled == 1
    assert repository.disabled_keys == {("removed_tool", "1.0")}


@pytest.mark.asyncio
async def test_indexer_counts_embedding_failures() -> None:
    summary = await ToolIndexer(
        one_tool_registry(),
        FakeRepository(),
        FakeEmbeddings(error=True),
    ).sync_registry()

    assert summary.failed == 1
    assert summary.inserted == 0


@pytest.mark.asyncio
async def test_indexer_rejects_duplicate_name_and_version() -> None:
    tool = one_tool_registry().list_all()[0]

    class DuplicateRegistry:
        def list_all(self) -> tuple[Any, ...]:
            return (tool, tool)

    with pytest.raises(ValueError, match="duplicate"):
        await ToolIndexer(
            DuplicateRegistry(),  # type: ignore[arg-type]
            FakeRepository(),
            FakeEmbeddings(),
        ).sync_registry()


def test_content_hash_is_stable_and_sensitive_to_metadata() -> None:
    tool = one_tool_registry().list_all()[0]
    text = build_tool_embedding_text(tool)
    changed = build_tool_embedding_text(
        tool.model_copy(update={"description": tool.description + " mới"})
    )

    assert calculate_content_hash(text) == calculate_content_hash(text)
    assert calculate_content_hash(text) != calculate_content_hash(changed)
