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
        async with database.session() as session:
            summary = await ToolIndexer(
                build_tool_registry(),
                SqlAlchemyToolEmbeddingRepository(session),
                embeddings,
            ).sync_registry()
        print(json.dumps(summary.model_dump(), ensure_ascii=False))
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
