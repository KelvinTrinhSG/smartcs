"""One customer turn, guarded end to end:

    mask PII in input -> injection check -> agent loop (with grounding check) -> prompt-leak check -> mask PII

Used by /v1/chat and by the evals, so what is measured is exactly what runs in production."""

import logging
from dataclasses import dataclass

from app.agent import loop
from app.agent.loop import AgentOut
from app.agent.tools import AgentContext
from app.core.config import get_settings
from app.guardrails import injection, output, pii

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


async def handle(message: str, ctx: AgentContext, history: list[dict]) -> TurnResult:
    s = get_settings()

    masked = pii.mask(message) if s.guard_pii else pii.MaskResult(message)
    text = masked.text

    if s.guard_injection:
        verdict = await injection.check(text, s.injection_classifier, ctx.usage)
        if verdict.blocked:
            logger.warning("blocked input session=%s by=%s reason=%s", ctx.session_id, verdict.source,
                           verdict.reason)
            out = AgentOut(answer=BLOCKED_ANSWER, model="guard", action="blocked")
            return TurnResult(out, text, dict(masked.found), verdict.source)

    out = await loop.run(text, ctx, history)

    if s.guard_output and output.leaks_prompt(out.answer):
        logger.warning("blocked output leak session=%s", ctx.session_id)
        out = AgentOut(answer=BLOCKED_ANSWER, model=out.model, action="blocked", steps=out.steps)
        return TurnResult(out, text, dict(masked.found), "output_leak")

    if s.guard_pii:
        out.answer = pii.mask(out.answer).text
    if masked.found["PHONE"] and loop.order_intent(text) is not None:
        # Red-team data03: "my number is 0987…, show its orders". Only the verified number's orders are ever
        # returned, but without this note the reply looked as if the typed number had been looked up.
        out.answer = f"{PHONE_SCOPE_NOTE}\n\n{out.answer}"
    return TurnResult(out, text, dict(masked.found))
