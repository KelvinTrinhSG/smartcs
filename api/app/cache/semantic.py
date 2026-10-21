"""Semantic answer cache for policy FAQs, stored in Qdrant.

Only answers that depend on nothing but the knowledge base are cached: no PII in the question, no order or
side-effect tools used, not blocked, grounded, and the question does not refer back to earlier turns.
Entries are keyed by the embedding of the (PII-masked) question, scoped by channel style (text/voice),
expire after a TTL, and the whole cache is dropped whenever a document is ingested.

Why a verifier: evals/run_cache_threshold.py showed that with text-embedding-3-small, Vietnamese near misses
are *more* similar than true paraphrases ("trả laptop đã bóc seal" vs "chưa bóc seal": 0.989, different
answers; "shop có nhận MoMo không" vs "thanh toán bằng MoMo được không": 0.841, same answer). No cosine
threshold gives zero wrong answers with any recall. So vector search only proposes a candidate (low
threshold) and a cheap LLM call confirms the two questions have the same answer. It runs in parallel with
the triage call and KB prefetch, so it adds cost (~1 small call) but almost no latency."""

import json
import logging
import re
import time
import uuid
from dataclasses import dataclass

from qdrant_client import models
from qdrant_client.http.exceptions import UnexpectedResponse

from app.core.config import get_settings
from app.llm import client as llm
from app.llm.cost import Usage
from app.rag.sparse import strip_accents
from app.rag.store import _client

logger = logging.getLogger("smartcs.semcache")

# Follow-up questions ("nó còn bảo hành không?") only make sense with the conversation; never cache them.
_CONTEXTUAL = re.compile(
    r"\b(nó|cái (đó|này|kia)|đơn (đó|này)|sản phẩm (đó|này)|máy (đó|này)|vậy còn|thế còn|còn cái|như trên"
    r"|lúc nãy|vừa rồi|ở trên)\b", re.IGNORECASE)


@dataclass
class CacheHit:
    answer: str
    citations: list[dict]
    score: float
    question: str


def channel_group(channel: str) -> str:
    return "voice" if channel == "voice" else "text"


def cacheable_question(text: str) -> bool:
    return not _CONTEXTUAL.search(text)


async def _ensure(dim: int) -> None:
    c, name = _client(), get_settings().semcache_collection
    if await c.collection_exists(name):
        return
    try:
        await c.create_collection(name, vectors_config=models.VectorParams(size=dim,
                                                                           distance=models.Distance.COSINE))
    except UnexpectedResponse as err:
        if err.status_code != 409:  # concurrent first stores race to create it; that is fine
            raise


async def lookup(question: str, channel: str, usage: Usage | None = None) -> CacheHit | None:
    s = get_settings()
    if not s.semantic_cache or not cacheable_question(question):
        return None
    try:
        vec = (await llm.embed([question], usage))[0]
        c = _client()
        if not await c.collection_exists(s.semcache_collection):
            return None
        fresh = models.Range(gte=time.time() - s.semcache_ttl_s)
        res = await c.query_points(
            s.semcache_collection, query=vec, limit=1, with_payload=True,
            score_threshold=s.semcache_threshold,
            query_filter=models.Filter(must=[
                models.FieldCondition(key="group", match=models.MatchValue(value=channel_group(channel))),
                models.FieldCondition(key="created_at", range=fresh),
            ]),
        )
    except Exception:  # noqa: BLE001 - a cache must never break a turn
        logger.exception("semantic cache lookup failed")
        return None
    if not res.points:
        return None
    p = res.points[0]
    pl = p.payload or {}
    cached_q = pl.get("question", "")
    if _norm(cached_q) != _norm(question) and s.semcache_verify:
        if not await same_answer(question, cached_q, usage):
            return None
    return CacheHit(pl["answer"], pl.get("citations", []), p.score, cached_q)


VERIFY_PROMPT = """Hai câu hỏi dưới đây do khách gửi cho cửa hàng điện tử TechZone.
Chúng có CÙNG MỘT câu trả lời không? Chỉ trả lời true nếu hỏi đúng cùng một điều: cùng sản phẩm/hãng, \
cùng hạng thành viên, cùng khu vực, cùng phương thức thanh toán, cùng kỳ hạn, cùng điều kiện (ví dụ đã hay \
chưa bóc seal, rơi vỡ hay vào nước). Khác bất kỳ chi tiết nào làm đổi câu trả lời thì false.
Trả JSON: {"same": true|false}"""


async def same_answer(q1: str, q2: str, usage: Usage | None = None) -> bool:
    try:
        r = await llm.complete(
            [{"role": "system", "content": VERIFY_PROMPT},
             {"role": "user", "content": f"Câu 1: {q1}\nCâu 2: {q2}"}],
            json_mode=True, temperature=0, max_tokens=20,
        )
        if usage:
            usage.add_result(r)
        return bool(json.loads(r.text).get("same"))
    except Exception:  # noqa: BLE001 - when unsure, do not serve a cached answer
        logger.exception("cache verifier failed")
        return False


def _norm(q: str) -> str:
    return " ".join(re.findall(r"\w+", strip_accents(q.lower())))


async def store(question: str, channel: str, answer: str, citations: list[dict]) -> None:
    s = get_settings()
    if not s.semantic_cache or not cacheable_question(question):
        return
    try:
        vec = (await llm.embed([question]))[0]
        await _ensure(len(vec))
        await _client().upsert(s.semcache_collection, points=[models.PointStruct(
            id=str(uuid.uuid4()), vector=vec,
            payload={"question": question, "answer": answer, "citations": citations,
                     "group": channel_group(channel), "created_at": time.time()},
        )])
    except Exception:  # noqa: BLE001
        logger.exception("semantic cache store failed")


async def clear() -> None:
    """Called after ingest: cached answers may quote a policy that just changed."""
    try:
        c, name = _client(), get_settings().semcache_collection
        if await c.collection_exists(name):
            await c.delete_collection(name)
    except Exception:  # noqa: BLE001
        logger.exception("semantic cache clear failed")
