from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    openai_api_key: str = ""
    llm_model_small: str = "gpt-4o-mini"
    llm_model_large: str = "gpt-4o"
    llm_max_tokens: int = 512
    llm_timeout_s: float = 30.0

    internal_api_key: str = ""

    database_url: str = ""
    redis_url: str = ""
    qdrant_url: str = ""
    n8n_base_url: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()
