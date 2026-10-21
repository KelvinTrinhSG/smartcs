import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings, get_settings
from app.main import app, get_repo
from tests.conftest import FakeRepo, tool_call

KEY = "test-key"


@pytest.fixture
def client(script, fake_retrieve):
    repo = FakeRepo(phone_by_user={"tg_7": "0901234567"})
    app.dependency_overrides[get_settings] = lambda: Settings(internal_api_key=KEY)
    app.dependency_overrides[get_repo] = lambda: repo
    with TestClient(app) as c:
        yield c, repo, script
    app.dependency_overrides.clear()


def body(channel="telegram", user="tg_7"):
    return {"session_id": "tg_7", "channel": channel, "user": {"id": user},
            "message": "ASUS bảo hành bao lâu?"}


def post(c, b, path="/v1/chat"):
    return c.post(path, json=b, headers={"X-Internal-Key": KEY})


def test_healthz(client):
    c, _, _ = client
    assert c.get("/healthz").json() == {"status": "ok"}


def test_chat_requires_internal_key(client):
    c, _, _ = client
    assert c.post("/v1/chat", json=body()).status_code == 401
    assert c.post("/v1/chat", json=body(), headers={"X-Internal-Key": "wrong"}).status_code == 401


def test_chat_runs_agent_and_persists_turn(client):
    c, repo, script = client
    script([
        [tool_call("lookup_order", {})],
        {"answer": "24 tháng.", "citations": ["policy_warranty#0"]},
    ])
    data = post(c, body()).json()
    assert data["answer"] == "24 tháng."
    assert data["citations"][0]["doc_id"] == "policy_warranty"
    assert data["meta"]["tools"] == ["search_kb", "lookup_order"] and data["meta"]["steps"] == 2
    assert repo.turns == [("tg_7", "ASUS bảo hành bao lâu?", "24 tháng.")]


def test_voice_channel_uses_voice_prompt(client):
    c, _, script = client
    s = script([{"answer": "ok", "citations": []}])
    post(c, body("voice"))
    assert "giọng nói" in s.calls[0][0]["content"]


def test_rejects_unknown_channel(client):
    c, _, _ = client
    assert post(c, body("sms")).status_code == 422


@pytest.mark.parametrize("raw, stored", [("+84 901 234 567", "0901234567"), ("84901234567", "0901234567"),
                                         ("0901234567", "0901234567")])
def test_verify_normalises_phone(client, raw, stored):
    c, repo, _ = client
    r = post(c, {"user_id": "tg_99", "phone": raw}, "/v1/verify")
    assert r.status_code == 200 and r.json()["phone_masked"] == "09******67"
    assert repo.phone_by_user["tg_99"] == stored


def test_verify_rejects_non_telegram_user_and_bad_phone(client):
    c, _, _ = client
    assert post(c, {"user_id": "web_1", "phone": "0901234567"}, "/v1/verify").status_code == 422
    assert post(c, {"user_id": "tg_1", "phone": "12345"}, "/v1/verify").status_code == 422


def test_ingest_requires_exactly_one_source(client):
    c, _, _ = client
    assert post(c, {"doc_id": "x"}, "/v1/ingest").status_code == 422
