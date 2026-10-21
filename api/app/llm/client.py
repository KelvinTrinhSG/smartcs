from dataclasses import dataclass

import litellm

from app.core.config import get_settings


@dataclass
class LLMResult:
    text: str
    model: str
    tokens_in: int
    tokens_out: int
    cost_usd: float


async def complete(messages: list[dict], model: str | None = None) -> LLMResult:
    settings = get_settings()
    model = model or settings.llm_model_small
    resp = await litellm.acompletion(
        model=model,
        messages=messages,
        max_tokens=settings.llm_max_tokens,
        timeout=settings.llm_timeout_s,
        api_key=settings.openai_api_key or None,
    )
    usage = resp.usage
    try:
        cost = float(litellm.completion_cost(completion_response=resp))
    except Exception:  # noqa: BLE001 - unknown model pricing must not fail the request
        cost = 0.0
    return LLMResult(
        text=resp.choices[0].message.content or "",
        model=model,
        tokens_in=usage.prompt_tokens,
        tokens_out=usage.completion_tokens,
        cost_usd=cost,
    )
