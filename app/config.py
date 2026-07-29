from functools import lru_cache
from typing import Literal

from pydantic import AnyHttpUrl, Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.common.constants import DEFAULT_EMBEDDING_DIMENSION


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

    llm_provider: Literal["ollama", "groq"] = "ollama"
    ollama_base_url: AnyHttpUrl
    ollama_chat_model: str = Field(min_length=1)
    ollama_embedding_model: str = Field(min_length=1)
    ollama_timeout_seconds: float = Field(gt=0)
    ollama_keep_alive: str = Field(default="30m", min_length=2, max_length=16)
    groq_base_url: AnyHttpUrl = AnyHttpUrl(
        "https://api.groq.com/openai/v1"
    )
    groq_api_key: SecretStr | None = None
    groq_chat_model: str = Field(default="qwen/qwen3.6-27b", min_length=1)
    groq_classifier_model: str | None = Field(default=None, min_length=1)
    groq_selector_model: str | None = Field(default=None, min_length=1)
    groq_response_model: str | None = Field(default=None, min_length=1)
    groq_timeout_seconds: float = Field(default=60, gt=0)
    groq_reasoning_effort: Literal["none", "low", "medium", "high"] = "none"
    groq_temperature: float = Field(default=0.1, ge=0, le=2)
    llm_max_retries: int = Field(default=1, ge=0, le=1)
    llm_max_retry_after_seconds: float = Field(default=3, ge=0, le=10)
    llm_structured_repair_attempts: int = Field(default=1, ge=0, le=1)
    tool_embedding_dimension: int = Field(
        default=DEFAULT_EMBEDDING_DIMENSION,
        gt=0,
    )

    database_url: str = Field(min_length=1)
    tool_top_k: int = Field(gt=0)
    tool_fetch_k: int = Field(gt=0)
    tool_min_score: float = Field(ge=0, le=1)
    tool_selection_min_confidence: float = Field(default=0.80, ge=0, le=1)
    sensitive_tool_selection_min_confidence: float = Field(
        default=0.85, ge=0, le=1
    )
    write_tool_selection_min_confidence: float = Field(
        default=0.90, ge=0, le=1
    )
    tool_min_margin: float = Field(default=0.05, ge=0, le=1)
    pending_action_ttl_seconds: int = Field(default=900, gt=0)
    pending_execution_lease_seconds: int = Field(default=30, gt=0)
    conversation_state_ttl_seconds: int = Field(default=86400, gt=0)
    max_workflow_steps_per_request: int = Field(default=20, ge=5, le=100)
    max_tool_calls_per_request: int = Field(default=1, ge=1, le=1)
    tool_selector_max_candidates: int = Field(default=3, ge=1, le=10)
    tool_selector_examples_per_kind: int = Field(default=2, ge=1, le=5)
    chatbot_ingress_api_key: SecretStr = SecretStr("change-me")

    @model_validator(mode="after")
    def validate_llm_provider(self) -> "Settings":
        if self.llm_provider == "groq" and self.groq_api_key is None:
            raise ValueError("GROQ_API_KEY is required for the Groq provider")
        structured_models = (
            self.groq_classifier_model or self.groq_chat_model,
            self.groq_selector_model or self.groq_chat_model,
        )
        if any("compound" in model.lower() for model in structured_models):
            raise ValueError(
                "Groq Compound models are not supported for structured routing"
            )
        if (
            not self.app_debug
            and self.chatbot_ingress_api_key.get_secret_value() == "change-me"
        ):
            raise ValueError(
                "CHATBOT_INGRESS_API_KEY must be changed outside debug mode"
            )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
