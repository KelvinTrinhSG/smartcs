from app.rag.retriever import Candidate
from app.schemas import Citation


def validate(cited_ids: list, context: list[Candidate]) -> list[Citation]:
    """Keep only citations that point at chunks actually given to the model (dedup, keep order)."""
    by_id = {c.hit.chunk_id: c.hit for c in context}
    out: list[Citation] = []
    seen: set[str] = set()
    for cid in cited_ids:
        if not isinstance(cid, str) or cid in seen or cid not in by_id:
            continue
        seen.add(cid)
        hit = by_id[cid]
        out.append(Citation(doc_id=hit.doc_id, chunk_id=cid, title=hit.title, section=hit.section))
    return out
