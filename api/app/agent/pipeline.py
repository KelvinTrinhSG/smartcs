"""One customer turn, guarded end to end:

    mask PII ─► ┌ injection rules + triage (attack? complex?) ┐
                ├ semantic cache lookup                       ├─► blocked | cached answer | agent loop
                └ KB / order prefetch (read-only)             ┘      (model chosen by the router)
             ─► prompt-leak check ─► PII mask ─► store in cache when safe

The three middle steps are independent and run concurrently (Week 5: hides the triage latency).
Used by /v1/chat and by the evals, so what is measured is exactly what runs in production."""

import asyncio
import logging
from dataclasses import dataclass

from app.agent import loop
from app.agent.loop import AgentOut
from app.agent.tools import AgentContext
from app.cache import semantic
from app.core.config import get_settings
from app.guardrails import injection, output, pii
from app.schemas import Citation

logger = logging.getLogger("smartcs.pipeline")

BLOCKED_ANSWER = (
    "Xin lỗi, mình chỉ có thể hỗ trợ các câu hỏi về sản phẩm, đơn hàng và chính sách của TechZone. "
    "Bạn cần mình giúp gì về mua sắm hoặc bảo hành không?"
)
PHONE_SCOPE_NOTE = (
    "Lưu ý: vì lý do bảo mật, mình chỉ tra được đơn hàng của số điện thoại bạn đã xác minh qua Telegram, "
    "không tra theo số được gõ trong tin nhắn."
)


@dataclass
class TurnResult:
    out: AgentOut
    masked_input: str
    pii_found: dict
    blocked_by: str = ""  # "", "rule:<name>", "classifier", "output_leak"
    route: str = "small"  # small | large | cache | blocked
    cache_score: float = 0.0


def _cacheable_turn(out: AgentOut, ctx: AgentContext) -> bool:
    """Only answers that depend on the knowledge base alone may be reused for other customers."""
    return (
        out.action == "none"
        and bool(out.citations)
        and out.grounding in ("skipped", "supported", "rewritten")
        and all(t["tool"] == "search_kb" for t in ctx.tool_log)
    )


async def handle(message: str, ctx: AgentContext, history: list[dict]) -> TurnResult:
    s = get_settings()

    masked = pii.mask(message) if s.guard_pii else pii.MaskResult(message)
    text = masked.text
    found = dict(masked.found)
    cache_ok = (s.semantic_cache and not masked.changed and loop.order_intent(text) is None
                and semantic.cacheable_question(text))

    async def triage() -> injection.Verdict:
        if not s.guard_injection:
            return injection.Verdict(False)
        return await injection.check(text, s.injection_classifier, ctx.usage)

    async def cache_lookup() -> semantic.CacheHit | None:
        return await semantic.lookup(text, ctx.channel, ctx.usage) if cache_ok else None

    async def prefetch() -> list[dict]:
        return await loop.prepare(text, ctx) if s.auto_retrieve else []

    # The prefetch (embedding + rerank call) is the slowest of the three; a blocked message or a cache hit
    # does not need it, so it is cancelled instead of awaited in those cases.
    prefetch_task = asyncio.create_task(prefetch())
    verdict, hit = await asyncio.gather(triage(), cache_lookup())

    if verdict.blocked or hit:
        prefetch_task.cancel()
    if verdict.blocked:
        logger.warning("blocked input session=%s by=%s reason=%s", ctx.session_id, verdict.source,
                       verdict.reason)
        out = AgentOut(answer=BLOCKED_ANSWER, model="guard", action="blocked")
        return TurnResult(out, text, found, verdict.source, route="blocked")

    if hit:
        out = AgentOut(answer=hit.answer, model="cache", citations=[Citation(**c) for c in hit.citations],
                       grounding="cached")
        return TurnResult(out, text, found, route="cache", cache_score=hit.score)

    prepared = await prefetch_task
    complex_turn = s.router_enabled and verdict.complexity == "complex"
    model = s.llm_model_large if complex_turn else s.llm_model_small
    out = await loop.run(text, ctx, history, prepared=prepared, model=model)

    if s.guard_output and output.leaks_prompt(out.answer):
        logger.warning("blocked output leak session=%s", ctx.session_id)
        out = AgentOut(answer=BLOCKED_ANSWER, model=out.model, action="blocked", steps=out.steps)
        return TurnResult(out, text, found, "output_leak", route="blocked")

    if s.guard_pii:
        out.answer = pii.mask(out.answer).text
    if masked.found["PHONE"] and loop.order_intent(text) is not None:
        # Red-team data03: "my number is 0987…, show its orders". Only the verified number's orders are ever
        # returned, but without this note the reply looked as if the typed number had been looked up.
        out.answer = f"{PHONE_SCOPE_NOTE}\n\n{out.answer}"

    if cache_ok and _cacheable_turn(out, ctx):
        await semantic.store(text, ctx.channel, out.answer, [c.model_dump() for c in out.citations])

    return TurnResult(out, text, found, route="large" if complex_turn else "small")
