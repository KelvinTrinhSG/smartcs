import json

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings, get_settings
from app.llm import client as llm
from app.main import app
from app.rag import retriever
from app.rag.retriever import Candidate
from app.rag.store import Hit

KEY = "test-key"

CONTEXT = [
    Candidate(
        hit=Hit("policy_warranty#0", "policy_warranty", "Chính sách bảo hành", "1. Thời hạn",
                "Laptop: 12 tháng (riêng ASUS Vivobook: 24 tháng).", 0.8),
        dense_score=0.8,
        rrf_score=0.03,
    )
]


@pytest.fixture
def client(monkeypatch):
    app.dependency_overrides[get_settings] = lambda: Settings(internal_api_key=KEY)
    state = {"context": CONTEXT, "reply": {"answer": "24 tháng.", "citations": ["policy_warranty#0"]}}

    async def fake_retrieve(query, usage=None, store=None):
        return state["context"]

    async def fake_complete(messages, model=None, **kwargs):
        state["messages"] = messages
        return llm.LLMResult(json.dumps(state["reply"]), "fake", 10, 3, 0.0001)

    monkeypatch.setattr(retriever, "retrieve", fake_retrieve)
    monkeypatch.setattr(llm, "complete", fake_complete)
    yield TestClient(app), state
    app.dependency_overrides.clear()


def body(channel="web"):
    return {"session_id": "s1", "channel": channel, "user": {"id": "u1"}, "message": "ASUS bảo hành bao lâu?"}


def post(c, b):
    return c.post("/v1/chat", json=b, headers={"X-Internal-Key": KEY})


def test_healthz(client):
    c, _ = client
    assert c.get("/healthz").json() == {"status": "ok"}


def test_chat_requires_internal_key(client):
    c, _ = client
    assert c.post("/v1/chat", json=body()).status_code == 401
    assert c.post("/v1/chat", json=body(), headers={"X-Internal-Key": "wrong"}).status_code == 401


def test_chat_returns_answer_with_valid_citation(client):
    c, state = client
    data = post(c, body()).json()
    assert data["answer"] == "24 tháng."
    assert data["citations"][0]["doc_id"] == "policy_warranty"
    assert data["meta"]["chunks_used"] == 1
    assert '<document id="policy_warranty#0"' in state["messages"][1]["content"]


def test_hallucinated_citation_is_dropped(client):
    c, state = client
    state["reply"] = {"answer": "x", "citations": ["policy_made_up#9", "policy_warranty#0"]}
    cites = post(c, body()).json()["citations"]
    assert [x["chunk_id"] for x in cites] == ["policy_warranty#0"]


def test_needs_handoff_maps_to_action(client):
    c, state = client
    state["context"] = []
    state["reply"] = {"answer": "Mình chưa có thông tin này.", "citations": [], "needs_handoff": True}
    data = post(c, body()).json()
    assert data["action"] == "handoff"
    assert "Không tìm thấy tài liệu" in state["messages"][1]["content"]


def test_non_json_reply_falls_back_to_text(client, monkeypatch):
    c, _ = client

    async def raw(messages, model=None, **kwargs):
        return llm.LLMResult("plain text", "fake", 1, 1, 0.0)

    monkeypatch.setattr(llm, "complete", raw)
    data = post(c, body()).json()
    assert data["answer"] == "plain text" and data["citations"] == []


def test_voice_channel_uses_voice_prompt(client):
    c, state = client
    post(c, body("voice"))
    assert "giọng nói" in state["messages"][0]["content"]


def test_rejects_unknown_channel(client):
    c, _ = client
    assert post(c, body("sms")).status_code == 422


def test_ingest_requires_exactly_one_source(client):
    c, _ = client
    r = c.post("/v1/ingest", json={"doc_id": "x"}, headers={"X-Internal-Key": KEY})
    assert r.status_code == 422
