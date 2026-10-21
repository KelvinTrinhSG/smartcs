"""Grounding check: are the factual claims in the answer supported by what the tools returned?

v1 asked gpt-4o-mini for a supported/unsupported verdict. Eval showed it hallucinated in the checker
itself: it flagged "Diamond: xử lý trong 3 ngày làm việc" as unsupported although that sentence is in
the retrieved document, and the agent then refused 3 correct answers. v2 makes the model *quote* the
evidence for every claim and verifies each quote in code; only claims without a verifiable quote count
as unsupported, so the LLM can no longer decide either way on its own."""

import json
import logging
import re
import unicodedata
from dataclasses import dataclass, field

from app.llm import client as llm
from app.llm.cost import Usage

logger = logging.getLogger("smartcs.grounding")

PROMPT = """Bạn kiểm tra câu trả lời của chatbot chăm sóc khách hàng so với BẰNG CHỨNG \
(kết quả công cụ và hội thoại trước).
Liệt kê từng khẳng định cụ thể trong CÂU TRẢ LỜI: số liệu, thời hạn, phí, chính sách, có/không, \
trạng thái đơn, đặc điểm sản phẩm, dịch vụ của cửa hàng. Bỏ qua lời chào, câu hỏi lại khách, \
đề nghị chuyển nhân viên, câu nói "chưa có thông tin", và hướng dẫn thao tác cho khách (bấm nút, xác minh \
số điện thoại, chờ nhân viên liên hệ).
Với mỗi khẳng định, chép NGUYÊN VĂN một đoạn ngắn trong BẰNG CHỨNG hỗ trợ nó. Được dùng kiến thức phổ \
thông để áp dụng tài liệu: ví dụ Đà Nẵng, Hải Phòng không thuộc Hà Nội/TP.HCM, nên "40.000đ các tỉnh khác" \
hỗ trợ "phí ship về Đà Nẵng là 40.000đ". Nếu không có đoạn nào hỗ trợ, để "quote": null.
Trả JSON: {"claims": [{"claim": "...", "quote": "<đoạn chép nguyên văn>" | null}]}"""


@dataclass
class GroundingResult:
    supported: bool
    unsupported_claims: list[str] = field(default_factory=list)


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFC", s).lower().replace("\\n", " ")
    s = re.sub(r"[*_#`\"“”'’]", " ", s)
    return " ".join(s.split())


def quote_in_evidence(quote: str, evidence: str) -> bool:
    q, ev = _norm(quote), _norm(evidence)
    if not q:
        return False
    if q in ev:
        return True
    # Tolerate small copy differences (punctuation, a dropped word): compare whole tokens, require 90% of
    # the quote's tokens and *every* number to appear, so "1 ngày" cannot match "120.000.000đ … 3 ngày".
    q_tokens, ev_tokens = re.findall(r"\w+", q), set(re.findall(r"\w+", ev))
    if len(q_tokens) < 3 or any(t not in ev_tokens for t in q_tokens if any(ch.isdigit() for ch in t)):
        return False
    return sum(t in ev_tokens for t in q_tokens) / len(q_tokens) >= 0.9


async def check(answer: str, evidence: list[str], history: list[dict], usage: Usage | None = None
                ) -> GroundingResult:
    convo = "\n".join(f"{m['role']}: {m['content']}" for m in history[-4:])
    ev_text = "\n\n".join(evidence)
    user = f"BẰNG CHỨNG:\n{ev_text or '(không có)'}\n\nHỘI THOẠI TRƯỚC:\n{convo or '(không có)'}\n\n" \
           f"CÂU TRẢ LỜI:\n{answer}"
    try:
        r = await llm.complete(
            [{"role": "system", "content": PROMPT}, {"role": "user", "content": user}],
            json_mode=True, temperature=0, max_tokens=500,
        )
        if usage:
            usage.add_result(r)
        claims = json.loads(r.text).get("claims") or []
    except Exception:  # noqa: BLE001 - a failed check must not block a reply
        logger.exception("grounding check failed")
        return GroundingResult(True)

    haystack = ev_text + "\n" + convo
    unsupported = [
        str(c.get("claim", ""))
        for c in claims
        if isinstance(c, dict) and not (c.get("quote") and quote_in_evidence(str(c["quote"]), haystack))
    ][:5]
    return GroundingResult(not unsupported, unsupported)
