"""Ingest a local folder: python -m app.rag.cli ingest /data/docs [--strategy section|fixed|recursive|all]"""

import argparse
import asyncio
from pathlib import Path

from app.llm.cost import Usage
from app.rag.chunking import STRATEGIES
from app.rag.ingest import ingest_document
from app.rag.loader import load_dir


async def _ingest(directory: Path, strategies: list[str]) -> None:
    docs = load_dir(directory)
    for strategy in strategies:
        usage = Usage()
        total = 0
        for doc in docs:
            n = await ingest_document(doc, strategy=strategy, usage=usage)
            total += n
            print(f"[{strategy}] {doc.doc_id}: {n} chunks")
        print(f"[{strategy}] total {total} chunks, {usage.tokens_in} tokens, ${usage.cost_usd:.6f}")


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("ingest")
    p.add_argument("directory", type=Path)
    p.add_argument("--strategy", default="section", choices=[*STRATEGIES, "all"])
    args = parser.parse_args()
    strategies = list(STRATEGIES) if args.strategy == "all" else [args.strategy]
    asyncio.run(_ingest(args.directory, strategies))


if __name__ == "__main__":
    main()
