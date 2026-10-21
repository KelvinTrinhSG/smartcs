import asyncio
from dataclasses import dataclass
from typing import Literal

from app.core.config import get_settings
from app.llm import client as llm
from app.llm.cost import Usage
from app.rag import rerank
from app.rag.store import Hit, KBStore, get_store

SearchMode = Literal["dense", "sparse", "hybrid"]
RRF_K = 60


@dataclass
class Candidate:
    hit: Hit
    dense_score: float | None
    rrf_score: float
    rerank_score: float | None = None


def rrf_fuse(dense: list[Hit], sparse: list[Hit], k: int = RRF_K) -> list[Candidate]:
    """Reciprocal Rank Fusion: rank-based, so dense and sparse scores need no calibration."""
    by_id: dict[str, Candidate] = {}
    for ranking, is_dense in ((dense, True), (sparse, False)):
        for rank, hit in enumerate(ranking):
            cand = by_id.setdefault(hit.chunk_id, Candidate(hit=hit, dense_score=None, rrf_score=0.0))
            cand.rrf_score += 1.0 / (k + rank + 1)
            if is_dense:
                cand.dense_score = hit.score
    return sorted(by_id.values(), key=lambda c: c.rrf_score, reverse=True)


async def search(
    query: str,
    store: KBStore,
    mode: SearchMode = "hybrid",
    limit: int = 10,
    usage: Usage | None = None,
    query_vector: list[float] | None = None,
) -> list[Candidate]:
    if mode == "sparse":
        return rrf_fuse([], await store.search_sparse(query, limit))
    if query_vector is None:
        query_vector = (await llm.embed([query], usage))[0]
    if mode == "dense":
        return rrf_fuse(await store.search_dense(query_vector, limit), [])
    dense, sparse_hits = await asyncio.gather(
        store.search_dense(query_vector, limit), store.search_sparse(query, limit)
    )
    return rrf_fuse(dense, sparse_hits)[:limit]


async def retrieve(query: str, usage: Usage | None = None, store: KBStore | None = None) -> list[Candidate]:
    """Hybrid search -> optional LLM rerank -> score threshold -> top_k chunks for the prompt."""
    settings = get_settings()
    cands = await search(query, store or get_store(), "hybrid", settings.retrieval_candidates, usage)

    if settings.rerank == "llm" and cands:
        cands = await rerank.llm_rerank(query, cands, usage)
        cands = [c for c in cands if (c.rerank_score or 0) >= settings.min_rerank_score]
    else:
        cands = [c for c in cands if c.dense_score is None or c.dense_score >= settings.min_dense_score]
    return cands[: settings.top_k]
