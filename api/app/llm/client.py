from dataclasses import dataclass

import litellm

from app.core.config import get_settings
from app.llm.cost import Usage

EMBED_BATCH = 100


@dataclass
class LLMResult:
    text: str
    model: str
    tokens_in: int
    tokens_out: int
    cost_usd: float


def _cost(resp) -> float:
    try:
        return float(litellm.completion_cost(completion_response=resp))
    except Exception:  # noqa: BLE001 - unknown model pricing must not fail the request
        return 0.0


async def complete(
    messages: list[dict],
    model: str | None = None,
    *,
    json_mode: bool = False,
    temperature: float | None = None,
    max_tokens: int | None = None,
) -> LLMResult:
    settings = get_settings()
    model = model or settings.llm_model_small
    kwargs = {}
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}
    if temperature is not None:
        kwargs["temperature"] = temperature
    resp = await litellm.acompletion(
        model=model,
        messages=messages,
        max_tokens=max_tokens or settings.llm_max_tokens,
        timeout=settings.llm_timeout_s,
        num_retries=settings.llm_retries,
        api_key=settings.openai_api_key or None,
        **kwargs,
    )
    usage = resp.usage
    return LLMResult(
        text=resp.choices[0].message.content or "",
        model=model,
        tokens_in=usage.prompt_tokens,
        tokens_out=usage.completion_tokens,
        cost_usd=_cost(resp),
    )


async def embed(texts: list[str], usage: Usage | None = None) -> list[list[float]]:
    settings = get_settings()
    vectors: list[list[float]] = []
    for i in range(0, len(texts), EMBED_BATCH):
        resp = await litellm.aembedding(
            model=settings.embedding_model,
            input=texts[i : i + EMBED_BATCH],
            api_key=settings.openai_api_key or None,
            timeout=settings.llm_timeout_s,
            num_retries=settings.llm_retries,
        )
        vectors += [d["embedding"] if isinstance(d, dict) else d.embedding for d in resp.data]
        if usage:
            usage.add(tokens_in=getattr(resp.usage, "prompt_tokens", 0) or 0, cost_usd=_cost(resp))
    return vectors
