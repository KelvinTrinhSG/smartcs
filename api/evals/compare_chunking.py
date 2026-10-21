"""Retrieval-only comparison: 3 chunking strategies x 3 search modes (dense / sparse / hybrid).

    python -m evals.compare_chunking --docs /data/docs

Cheap: only embeddings are called (no generation). Writes evals/reports/<date>_chunking.md.
"""

import argparse
import asyncio
import datetime as dt
import statistics
from pathlib import Path

from app.llm import client as llm
from app.llm.cost import Usage
from app.rag import retriever
from app.rag.chunking import STRATEGIES, chunk
from app.rag.ingest import ingest_document
from app.rag.loader import load_dir
from app.rag.store import get_store
from evals.common import REPORTS, first_relevant_rank, load_golden, pct

MODES = ("dense", "sparse", "hybrid")
LIMIT = 10


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--docs", type=Path, default=Path("/data/docs"))
    args = parser.parse_args()

    docs = load_dir(args.docs)
    items = [i for i in load_golden() if i["type"] != "out_of_scope"]
    usage = Usage()
    qvecs = await llm.embed([i["question"] for i in items], usage)

    rows = []
    for strategy in STRATEGIES:
        store = get_store(strategy)
        for doc in docs:
            await ingest_document(doc, strategy=strategy, store=store, usage=usage)
        sizes = [len(c.text) for d in docs for c in chunk(d, strategy)]

        for mode in MODES:
            ranks = []
            for item, qv in zip(items, qvecs, strict=True):
                cands = await retriever.search(item["question"], store, mode, LIMIT, query_vector=qv)
                ranks.append(first_relevant_rank([c.hit for c in cands], item))
            rows.append({
                "strategy": strategy, "mode": mode, "chunks": len(sizes),
                "avg_chars": int(statistics.mean(sizes)),
                "hit1": sum(r == 1 for r in ranks) / len(ranks),
                "hit4": sum(r is not None and r <= 4 for r in ranks) / len(ranks),
                "mrr": sum(1 / r for r in ranks if r) / len(ranks),
            })
            print(rows[-1])

    lines = [
        f"# Chunking × search mode — {dt.date.today().isoformat()}",
        "",
        f"{len(items)} answerable questions, {len(docs)} documents. A hit = chunk from the expected doc "
        "containing the evidence phrase. Retrieval only, no rerank.",
        "",
        "| Chunking | Search | Chunks | Avg chars | Hit@1 | Hit@4 | MRR@10 |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        lines.append(
            f"| {r['strategy']} | {r['mode']} | {r['chunks']} | {r['avg_chars']} | "
            f"{pct(r['hit1'])} | {pct(r['hit4'])} | {r['mrr']:.3f} |"
        )
    lines.append(f"\nEmbedding cost for this run: ${usage.cost_usd:.5f}")
    REPORTS.mkdir(exist_ok=True)
    out = REPORTS / f"{dt.date.today().isoformat()}_chunking.md"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    asyncio.run(main())
