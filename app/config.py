from functools import lru_cache

from pydantic import AnyHttpUrl, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str
    app_host: str
    app_port: int = Field(ge=1, le=65535)
    app_debug: bool

    odoo_base_url: AnyHttpUrl
    odoo_database: str = Field(min_length=1)
    odoo_internal_api_key: SecretStr
    odoo_connect_timeout_seconds: float = Field(gt=0)
    odoo_read_timeout_seconds: float = Field(gt=0)

    ollama_base_url: AnyHttpUrl
    ollama_chat_model: str = Field(min_length=1)
    ollama_embedding_model: str = Field(min_length=1)
    ollama_timeout_seconds: float = Field(gt=0)

    database_url: str = Field(min_length=1)
    tool_top_k: int = Field(gt=0)
    tool_fetch_k: int = Field(gt=0)
    tool_min_score: float = Field(ge=0, le=1)


@lru_cache
def get_settings() -> Settings:
    return Settings()
