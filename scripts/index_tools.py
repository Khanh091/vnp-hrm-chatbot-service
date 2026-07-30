import asyncio
import json

from app.config import get_settings
from app.persistence.database import Database
from app.persistence.repositories.tool_embedding_repository import (
    SqlAlchemyToolEmbeddingRepository,
)
from app.retrieval.embeddings import OllamaEmbeddingProvider
from app.retrieval.tool_indexer import ToolIndexer
from app.tools import build_tool_registry


async def run() -> int:
    settings = get_settings()
    database = Database(settings.database_url)
    embeddings = OllamaEmbeddingProvider(settings)
    try:
        registry = build_tool_registry()
        async with database.session() as session:
            repository = SqlAlchemyToolEmbeddingRepository(session)
            summary = await ToolIndexer(
                registry,
                repository,
                embeddings,
            ).sync_registry()
            indexed_records = await repository.list_records()
        registry_names = {tool.name for tool in registry.list_all()}
        enabled_registry_names = {
            tool.name for tool in registry.list_all() if tool.enabled
        }
        indexed_names = {
            record.tool_name for record in indexed_records if record.enabled
        }
        if enabled_registry_names != indexed_names:
            raise RuntimeError("enabled registry and index tool names differ")
        output = {
            **summary.model_dump(),
            "registry_count": len(registry_names),
            "enabled_count": len(enabled_registry_names),
            "indexed_count": len(indexed_names),
            "registry_index_match": True,
        }
        print(json.dumps(output, ensure_ascii=False))
        return 1 if summary.failed else 0
    except Exception as error:
        print(
            json.dumps(
                {
                    "success": False,
                    "error": type(error).__name__,
                }
            )
        )
        return 1
    finally:
        await embeddings.close()
        await database.close()


def main() -> None:
    raise SystemExit(asyncio.run(run()))


if __name__ == "__main__":
    main()
