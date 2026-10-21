from functools import lru_cache
from typing import Literal

from pydantic import field_validator
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

    # Guardrails (each can be switched off to measure its effect in evals/run_redteam.py)
    guard_pii: bool = True
    guard_injection: bool = True
    injection_classifier: bool = True
    # off | risk | always. "risk" checks only when the best rerank score of the evidence is below
    # grounding_skip_score: on the golden set that is ~15% of turns (weak or no evidence), where fabrication
    # happens; "always" doubled latency and caused false refusals with a gpt-4o-mini checker.
    grounding_mode: Literal["off", "risk", "always"] = "risk"
    grounding_skip_score: float = 10.0
    guard_output: bool = True
    # Cost / latency
    router_enabled: bool = True  # "complex" turns (from the triage call) use llm_model_large
    semantic_cache: bool = True
    semcache_collection: str = "semcache"
    # Candidate threshold only; every candidate is confirmed by an LLM verifier (semcache_verify).
    # Chosen by evals/run_cache_threshold.py: no cosine threshold alone was safe, see README.
    semcache_threshold: float = 0.60
    semcache_verify: bool = True
    semcache_ttl_s: int = 86400
    daily_budget_usd: float = 1.0

    rate_limit_per_minute: int = 15
    rate_limit_per_day: int = 300
    history_messages: int = 10

    internal_api_key: str = ""

    database_url: str = ""
    redis_url: str = ""
    qdrant_url: str = "http://localhost:6333"
    qdrant_api_key: str = ""  # Qdrant Cloud; empty for the local container

    # n8n tool webhooks. Render's private-network reference gives "host:port" without a scheme.
    n8n_base_url: str = "http://n8n:5678"

    @field_validator("n8n_base_url")
    @classmethod
    def _add_scheme(cls, v: str) -> str:
        return v if "://" in v else f"http://{v}"

    n8n_timeout_s: float = 10.0
    n8n_retries: int = 2
    n8n_backoff_s: float = 0.5


@lru_cache
def get_settings() -> Settings:
    return Settings()
