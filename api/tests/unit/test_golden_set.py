from pathlib import Path

from app.rag.loader import load_dir
from evals.common import _norm, load_golden

DOCS = {d.doc_id: d for d in load_dir(Path(__file__).resolve().parents[3] / "data" / "docs")}


def test_golden_set_evidence_exists_in_docs():
    for item in load_golden():
        if item["type"] in ("out_of_scope", "action"):
            assert item["expected_doc"] is None
            continue
        doc = DOCS[item["expected_doc"]]
        assert _norm(item["evidence"]) in _norm(doc.text), item["id"]


def test_action_items_name_a_real_tool():
    from app.agent.tools import TOOLS

    for item in load_golden():
        if item["type"] == "action":
            assert item["expected_tool"] in TOOLS, item["id"]


def test_golden_set_ids_unique():
    ids = [i["id"] for i in load_golden()]
    assert len(ids) == len(set(ids))
