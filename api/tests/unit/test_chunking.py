from pathlib import Path

import pytest

from app.rag.chunking import STRATEGIES, Document, chunk, fixed_windows, recursive_split
from app.rag.loader import load_dir

DOCS = Path(__file__).resolve().parents[3] / "data" / "docs"

SAMPLE = Document(
    doc_id="d",
    title="Chính sách",
    text="# Chính sách\n\n## 1. Thời hạn\n- Laptop: 12 tháng.\n\n## 2. Điều kiện\n### Tem\nCòn tem.\n",
)


@pytest.mark.parametrize("strategy", STRATEGIES)
def test_every_strategy_produces_ids_and_text(strategy):
    chunks = chunk(SAMPLE, strategy)
    assert chunks
    assert [c.chunk_id for c in chunks] == [f"d#{i}" for i in range(len(chunks))]
    assert all(c.text.strip() for c in chunks)
    assert "12 tháng" in " ".join(c.text for c in chunks)


def test_section_strategy_tracks_heading_path():
    sections = [c.section for c in chunk(SAMPLE, "section")]
    assert sections == ["1. Thời hạn", "2. Điều kiện > Tem"]


def test_fixed_windows_overlap_and_cover_text():
    text = " ".join(f"w{i}" for i in range(300))
    windows = fixed_windows(text, size=100, overlap=20)
    assert all(len(w) <= 100 for w in windows)
    assert windows[0].split()[0] == "w0" and windows[-1].split()[-1] == "w299"


def test_recursive_split_respects_max_chars():
    text = "\n\n".join("đoạn " * 40 for _ in range(5))
    assert all(len(p) <= 250 for p in recursive_split(text, 250))


@pytest.mark.parametrize("strategy", STRATEGIES)
def test_real_docs_chunk_under_limit(strategy):
    for doc in load_dir(DOCS):
        assert all(len(c.text) <= 600 for c in chunk(doc, strategy))
