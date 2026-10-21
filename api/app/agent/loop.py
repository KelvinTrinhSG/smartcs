"""Tool-use loop: the model calls tools until it produces a final JSON answer, bounded by max_steps."""

import asyncio
import json
import logging
import re
from dataclasses import dataclass, field

from app.agent import tools
from app.agent.prompts import agent_prompt
from app.agent.tools import AgentContext
from app.core.config import get_settings
from app.guardrails import grounding
from app.llm import client as llm
from app.rag import citation
from app.schemas import Citation

logger = logging.getLogger("smartcs.agent")

FALLBACK = (
    "Xin lỗi, mình chưa xử lý được yêu cầu này. Bạn có muốn mình chuyển cho nhân viên hỗ trợ không?"
)
# When several actions happen in one turn, the channel shows the most important one.
ACTION_PRIORITY = ("request_phone", "handoff", "ticket_created", "appointment_booked")


@dataclass
class AgentOut:
    answer: str
    model: str
    action: str = "none"
    citations: list[Citation] = field(default_factory=list)
    steps: int = 0
    grounding: str = "skipped"  # supported | rewritten | refused | unsupported_kept | skipped


def _action(ctx: AgentContext) -> str:
    return next((a for a in ACTION_PRIORITY if a in ctx.actions), "none")


def _final(text: str, model: str, ctx: AgentContext, steps: int) -> AgentOut:
    try:
        data = json.loads(text)
        answer = str(data.get("answer", "")).strip()
        cited = data.get("citations") or []
    except (json.JSONDecodeError, AttributeError):
        logger.warning("final answer was not valid JSON, returning raw text")
        answer, cited = text.strip(), []
    return AgentOut(
        answer=answer or FALLBACK,
        model=model,
        action=_action(ctx),
        citations=citation.validate(cited, list(ctx.retrieved.values())),
        steps=steps,
    )


ORDER_ID_RE = re.compile(r"\bTZ\d{5,}\b", re.IGNORECASE)
ORDER_INTENT_RE = re.compile(r"đơn hàng|mã đơn|đơn của|don hang|ma don", re.IGNORECASE)


def order_intent(question: str) -> dict | None:
    """Arguments for lookup_order if the message is clearly about the customer's own order."""
    m = ORDER_ID_RE.search(question)
    if m:
        return {"order_id": m.group(0).upper()}
    return {} if ORDER_INTENT_RE.search(question) else None


async def _inject(name: str, args: dict, ctx: AgentContext, messages: list[dict]) -> None:
    """Run a tool before the first LLM call and add it to the conversation as a normal tool turn,
    so the model sees the result and may still call tools again with other arguments."""
    raw = json.dumps(args, ensure_ascii=False)
    result = await tools.dispatch(name, raw, ctx)
    ctx.tool_log[-1]["auto"] = True
    call_id = f"prefetch_{name}"
    messages.append({
        "role": "assistant", "content": None,
        "tool_calls": [{"id": call_id, "type": "function", "function": {"name": name, "arguments": raw}}],
    })
    messages.append({"role": "tool", "tool_call_id": call_id,
                     "content": json.dumps(result, ensure_ascii=False, default=str)})


async def prepare(question: str, ctx: AgentContext) -> list[dict]:
    """Deterministic, read-only tool calls made before the first LLM turn (returned as messages).

    - search_kb with the customer's own words: when the model wrote its own query it paraphrased
      "Hải Phòng" away from "các tỉnh khác" and recall dropped. Also saves one LLM round trip.
    - lookup_order when the message is clearly about an order: the model sometimes told unverified
      customers to "tap the share-phone button" without calling the tool, so action=request_phone
      was never set and the button never appeared.
    Both are read-only, so the pipeline runs this in parallel with the injection/triage check."""
    messages: list[dict] = []
    await _inject("search_kb", {"query": question[:300]}, ctx, messages)
    order_args = order_intent(question)
    if order_args is not None:
        await _inject("lookup_order", order_args, ctx, messages)
    return messages


REWRITE = (
    "[KIỂM TRA NỘI BỘ] Câu trả lời vừa rồi có các ý không được kết quả công cụ hỗ trợ: {claims}. "
    "Viết lại câu trả lời chỉ dùng thông tin có trong kết quả công cụ. Với điều khách hỏi mà không có bằng "
    "chứng, nói rõ là bạn chưa có thông tin về chính điều đó và đề nghị chuyển nhân viên. Trả về JSON như cũ."
)
SAFE_REFUSAL = (
    "Xin lỗi, mình chưa có thông tin chắc chắn về vấn đề này. "
    "Bạn có muốn mình chuyển cho nhân viên hỗ trợ không?"
)
SIDE_EFFECTS = {"ticket_created", "appointment_booked", "handoff"}


def _needs_grounding(ctx: AgentContext) -> bool:
    mode = get_settings().grounding_mode
    if mode == "off":
        return False
    if mode == "always":
        return True
    scores = [c.rerank_score for c in ctx.retrieved.values() if c.rerank_score is not None]
    return not scores or max(scores) < get_settings().grounding_skip_score


async def _ground(out: AgentOut, messages: list[dict], ctx: AgentContext, history: list[dict]) -> AgentOut:
    """Check the answer against tool evidence; rewrite once without tools; refuse if still unsupported."""
    first = await grounding.check(out.answer, ctx.evidence, history, ctx.usage)
    if first.supported:
        out.grounding = "supported"
        return out
    logger.info("ungrounded answer session=%s claims=%s", ctx.session_id, first.unsupported_claims)

    retry = [
        *messages,
        {"role": "assistant", "content": json.dumps({"answer": out.answer}, ensure_ascii=False)},
        {"role": "system", "content": REWRITE.format(claims="; ".join(first.unsupported_claims))},
    ]
    r = await llm.complete(retry, json_mode=True, temperature=0)  # no tools: a rewrite must not act
    ctx.usage.add_result(r)
    rewritten = _final(r.text, r.model, ctx, out.steps + 1)
    second = await grounding.check(rewritten.answer, ctx.evidence, history, ctx.usage)
    if second.supported:
        rewritten.grounding = "rewritten"
        return rewritten
    if SIDE_EFFECTS & set(ctx.actions):
        # A ticket/booking already happened; the customer must still get its reference number.
        rewritten.grounding = "unsupported_kept"
        return rewritten
    return AgentOut(answer=SAFE_REFUSAL, model=r.model, action=_action(ctx), steps=rewritten.steps,
                    grounding="refused")


async def run(
    question: str,
    ctx: AgentContext,
    history: list[dict] | None = None,
    prepared: list[dict] | None = None,
    model: str | None = None,
) -> AgentOut:
    settings = get_settings()
    messages: list[dict] = [
        {"role": "system", "content": agent_prompt(ctx.channel, tools.now(), phone_verified=bool(ctx.phone))},
        *(history or []),
        {"role": "user", "content": question},
    ]
    if prepared is None and settings.auto_retrieve:
        prepared = await prepare(question, ctx)
    messages += prepared or []

    model = model or settings.llm_model_small
    for step in range(1, settings.agent_max_steps + 1):
        r = await llm.complete(messages, model, tools=tools.TOOL_SPECS, json_mode=True, temperature=0.2)
        ctx.usage.add_result(r)
        model = r.model
        if not r.tool_calls:
            out = _final(r.text, model, ctx, step)
            # A request_phone reply is verification guidance, not a factual claim: eval showed the checker
            # replacing it with "no information", which hid why the share-phone button appeared.
            if out.action != "request_phone" and _needs_grounding(ctx):
                out = await _ground(out, messages, ctx, history or [])
            return out

        messages.append(r.assistant_message())
        results = await asyncio.gather(
            *(tools.dispatch(tc["name"], tc["arguments"], ctx) for tc in r.tool_calls)
        )
        for tc, res in zip(r.tool_calls, results, strict=True):
            messages.append({
                "role": "tool",
                "tool_call_id": tc["id"],
                "content": json.dumps(res, ensure_ascii=False, default=str),
            })

    logger.warning("agent hit max_steps=%d session=%s", settings.agent_max_steps, ctx.session_id)
    return AgentOut(answer=FALLBACK, model=model, action=_action(ctx), steps=settings.agent_max_steps)
