from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.integrations.odoo.client import OdooClient
from app.integrations.odoo.schemas import OdooUserContext
from app.main import create_app


def build_settings() -> Settings:
    return Settings(
        _env_file=None,
        app_name="Test Chatbot",
        app_host="127.0.0.1",
        app_port=8000,
        app_debug=False,
        odoo_base_url="http://odoo.test",
        odoo_database="test",
        odoo_internal_api_key="test-key",
        odoo_connect_timeout_seconds=0.1,
        odoo_read_timeout_seconds=0.1,
        ollama_base_url="http://ollama.test",
        ollama_chat_model="test-chat",
        ollama_embedding_model="test-embedding",
        ollama_timeout_seconds=1,
        database_url="postgresql://test",
        tool_top_k=5,
        tool_fetch_k=20,
        tool_min_score=0.45,
    )


class StubOdooClient(OdooClient):
    async def get_current_user_context(
        self,
        *,
        odoo_user_id: int,
        request_id: str,
    ) -> OdooUserContext:
        return OdooUserContext(
            user_id=odoo_user_id,
            employee_id=10,
            company_id=1,
            department_id=4,
            timezone="Asia/Ho_Chi_Minh",
            language="vi_VN",
        )


@pytest.fixture
def client() -> Iterator[TestClient]:
    settings = build_settings()
    odoo_client = StubOdooClient(settings)
    with TestClient(
        create_app(settings=settings, odoo_client=odoo_client),
    ) as test_client:
        yield test_client
