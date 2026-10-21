from dataclasses import dataclass, field

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
    tool_calls: list[dict] = field(default_factory=list)  # [{"id", "name", "arguments"}]

    def assistant_message(self) -> dict:
        """The assistant turn to append to the conversation before sending tool results back."""
        msg: dict = {"role": "assistant", "content": self.text or None}
        if self.tool_calls:
            msg["tool_calls"] = [
                {"id": tc["id"], "type": "function",
                 "function": {"name": tc["name"], "arguments": tc["arguments"]}}
                for tc in self.tool_calls
            ]
        return msg


def _cost(resp) -> float:
    try:
        return float(litellm.completion_cost(completion_response=resp))
    except Exception:  # noqa: BLE001 - unknown model pricing must not fail the request
        return 0.0


async def complete(
    messages: list[dict],
    model: str | None = None,
    *,
    tools: list[dict] | None = None,
    json_mode: bool = False,
    temperature: float | None = None,
    max_tokens: int | None = None,
) -> LLMResult:
    settings = get_settings()
    model = model or settings.llm_model_small
    kwargs = {}
    if tools:
        kwargs["tools"] = tools
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
    message = resp.choices[0].message
    tool_calls = [
        {"id": tc.id, "name": tc.function.name, "arguments": tc.function.arguments or "{}"}
        for tc in (getattr(message, "tool_calls", None) or [])
    ]
    return LLMResult(
        text=message.content or "",
        model=model,
        tokens_in=usage.prompt_tokens,
        tokens_out=usage.completion_tokens,
        cost_usd=_cost(resp),
        tool_calls=tool_calls,
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
