from app.rag import sparse
from app.rag.citation import validate
from app.rag.retriever import Candidate, rrf_fuse
from app.rag.store import Hit


def hit(cid, score=0.5):
    return Hit(cid, cid.split("#")[0], "T", "S", "text", score)


def test_unaccented_query_matches_accented_doc():
    doc_idx, _ = sparse.doc_vector("Chính sách bảo hành laptop")
    q_idx, _ = sparse.query_vector("bao hanh")
    assert set(q_idx) <= set(doc_idx)


def test_bigrams_are_indexed():
    assert "bảo_hành" in sparse.tokens("Bảo hành")


def test_sparse_indices_are_unique_and_sorted():
    idx, vals = sparse.doc_vector("phí phí phí giao hàng")
    assert idx == sorted(set(idx)) and len(idx) == len(vals)


def test_rrf_rewards_agreement_between_rankers():
    dense = [hit("a#0", 0.9), hit("b#0", 0.8), hit("c#0", 0.7)]
    sparse_hits = [hit("b#0", 12), hit("c#0", 10)]
    fused = rrf_fuse(dense, sparse_hits)
    # b and c appear in both rankings, so they beat a (dense rank 1 only).
    assert [c.hit.chunk_id for c in fused] == ["b#0", "c#0", "a#0"]
    assert fused[0].dense_score == 0.8


def test_sparse_only_hit_has_no_dense_score():
    fused = rrf_fuse([], [hit("x#0", 3)])
    assert fused[0].dense_score is None


def test_citation_validation_keeps_only_context_ids():
    ctx = [Candidate(hit("a#0"), 0.9, 0.1), Candidate(hit("b#1"), 0.8, 0.1)]
    cites = validate(["b#1", "zzz#9", "b#1", 42, "a#0"], ctx)
    assert [c.chunk_id for c in cites] == ["b#1", "a#0"]
