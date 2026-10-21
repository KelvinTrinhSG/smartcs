from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    openai_api_key: str = ""
    llm_model_small: str = "gpt-4o-mini"
    llm_model_large: str = "gpt-4o"
    llm_max_tokens: int = 512
    llm_timeout_s: float = 30.0
    llm_retries: int = 2

    # RAG
    embedding_model: str = "text-embedding-3-small"
    kb_collection_prefix: str = "kb"
    chunk_strategy: Literal["fixed", "recursive", "section"] = "section"
    retrieval_candidates: int = 10
    top_k: int = 4
    rerank: Literal["llm", "none"] = "llm"
    min_rerank_score: float = 5.0
    min_dense_score: float = 0.3

    # Agent
    agent_max_steps: int = 5
    auto_retrieve: bool = True
    history_messages: int = 10

    internal_api_key: str = ""

    database_url: str = ""
    redis_url: str = ""
    qdrant_url: str = "http://localhost:6333"

    # n8n tool webhooks
    n8n_base_url: str = "http://n8n:5678"
    n8n_timeout_s: float = 10.0
    n8n_retries: int = 2
    n8n_backoff_s: float = 0.5


@lru_cache
def get_settings() -> Settings:
    return Settings()
