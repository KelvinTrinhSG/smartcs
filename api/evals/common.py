import json
import os
import unicodedata
from pathlib import Path

from app.rag.store import Hit

HERE = Path(__file__).parent
REPORTS = HERE / "reports"


def load_golden(path: Path = HERE / "golden_set.jsonl") -> list[dict]:
    return load_jsonl(path)


def load_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


DOCS_DIR = Path(os.environ.get("DOCS_DIR", "/data/docs"))
if not DOCS_DIR.exists():
    DOCS_DIR = HERE.parents[1] / "data" / "docs"


def doc_text(doc_id: str) -> str:
    return (DOCS_DIR / f"{doc_id}.md").read_text(encoding="utf-8")


def all_docs_text() -> str:
    return "\n\n".join(p.read_text(encoding="utf-8") for p in sorted(DOCS_DIR.glob("*.md")))


def _norm(s: str) -> str:
    return " ".join(unicodedata.normalize("NFC", s).lower().split())


def is_relevant(hit: Hit, item: dict) -> bool:
    """A chunk is relevant if it comes from the expected doc and contains the evidence phrase."""
    return hit.doc_id == item["expected_doc"] and _norm(item["evidence"]) in _norm(hit.text)


def first_relevant_rank(hits: list[Hit], item: dict) -> int | None:
    for i, h in enumerate(hits, start=1):
        if is_relevant(h, item):
            return i
    return None


def pct(x: float) -> str:
    return f"{x * 100:.1f}%"
