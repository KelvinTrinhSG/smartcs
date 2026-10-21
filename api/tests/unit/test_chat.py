import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings, get_settings
from app.llm import client as llm
from app.main import app

KEY = "test-key"


@pytest.fixture
def client(monkeypatch):
    app.dependency_overrides[get_settings] = lambda: Settings(internal_api_key=KEY)
    captured = {}

    async def fake_complete(messages, model=None):
        captured["messages"] = messages
        return llm.LLMResult(text="Xin chào!", model="fake", tokens_in=10, tokens_out=3, cost_usd=0.0)

    monkeypatch.setattr(llm, "complete", fake_complete)
    yield TestClient(app), captured
    app.dependency_overrides.clear()


def body(channel="web"):
    return {"session_id": "s1", "channel": channel, "user": {"id": "u1"}, "message": "Chào shop"}


def test_healthz(client):
    c, _ = client
    assert c.get("/healthz").json() == {"status": "ok"}


def test_chat_requires_internal_key(client):
    c, _ = client
    assert c.post("/v1/chat", json=body()).status_code == 401
    assert c.post("/v1/chat", json=body(), headers={"X-Internal-Key": "wrong"}).status_code == 401


def test_chat_ok(client):
    c, _ = client
    r = c.post("/v1/chat", json=body(), headers={"X-Internal-Key": KEY})
    assert r.status_code == 200
    data = r.json()
    assert data["answer"] == "Xin chào!"
    assert data["action"] == "none"
    assert data["meta"]["tokens_in"] == 10


def test_voice_channel_uses_voice_prompt(client):
    c, captured = client
    c.post("/v1/chat", json=body("voice"), headers={"X-Internal-Key": KEY})
    assert "giọng nói" in captured["messages"][0]["content"]


def test_rejects_unknown_channel(client):
    c, _ = client
    r = c.post("/v1/chat", json=body("sms"), headers={"X-Internal-Key": KEY})
    assert r.status_code == 422
