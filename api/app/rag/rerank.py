"""LLM-as-reranker: one cheap call scores all candidates (no extra model to host)."""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

from app.llm import client as llm
from app.llm.cost import Usage

if TYPE_CHECKING:
    from app.rag.retriever import Candidate

logger = logging.getLogger("smartcs.rerank")

PROMPT = """Bạn là bộ chấm điểm mức độ liên quan cho hệ thống tìm kiếm tài liệu.
Chấm mỗi đoạn từ 0 đến 10 theo mức độ đoạn đó chứa thông tin giúp trả lời câu hỏi
(10 = trả lời trực tiếp, 5 = có thông tin liên quan một phần, 0 = không liên quan).
Trả về JSON dạng {"scores": {"<id>": <điểm>, ...}} cho tất cả các đoạn."""


async def llm_rerank(query: str, cands: list[Candidate], usage: Usage | None = None) -> list[Candidate]:
    ids = [f"c{i}" for i in range(len(cands))]
    docs = "\n\n".join(
        f'<passage id="{pid}">\n{c.hit.section}\n{c.hit.text}\n</passage>'
        for pid, c in zip(ids, cands, strict=True)
    )
    messages = [
        {"role": "system", "content": PROMPT},
        {"role": "user", "content": f"Câu hỏi: {query}\n\n{docs}"},
    ]
    try:
        result = await llm.complete(messages, json_mode=True, temperature=0, max_tokens=300)
        if usage:
            usage.add_result(result)
        scores = json.loads(result.text).get("scores", {})
    except Exception:  # noqa: BLE001 - fall back to fusion order rather than failing the chat
        logger.exception("rerank failed, keeping fusion order")
        return cands

    for pid, c in zip(ids, cands, strict=True):
        try:
            c.rerank_score = float(scores.get(pid, 0))
        except (TypeError, ValueError):
            c.rerank_score = 0.0
    return sorted(cands, key=lambda c: c.rerank_score or 0, reverse=True)
