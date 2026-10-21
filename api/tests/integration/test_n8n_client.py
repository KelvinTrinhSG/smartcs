"""n8n webhooks mocked at the HTTP layer with respx: retries, idempotency, auth header, timeouts."""

import json

import httpx
import pytest
import respx

from app.agent import n8n_client
from app.agent.n8n_client import ToolError
from app.core.config import Settings, get_settings

URL = "http://n8n.test/webhook/tool/create-ticket"
PAYLOAD = {"idempotency_key": "s:t:create_ticket", "summary": "x"}


@pytest.fixture(autouse=True)
def settings(monkeypatch):
    s = Settings(n8n_base_url="http://n8n.test", internal_api_key="secret", n8n_retries=2, n8n_backoff_s=0)
    monkeypatch.setattr(n8n_client, "get_settings", lambda: s)
    get_settings.cache_clear()
    return s


@respx.mock
async def test_retries_on_503_with_same_idempotency_key():
    route = respx.post(URL).mock(side_effect=[
        httpx.Response(503),
        httpx.Response(200, json={"ticket_id": "TK1001", "status": "open"}),
    ])
    res = await n8n_client.call_tool("create-ticket", PAYLOAD)
    assert res["ticket_id"] == "TK1001"
    assert route.call_count == 2
    keys = {json.loads(c.request.content)["idempotency_key"] for c in route.calls}
    assert keys == {"s:t:create_ticket"}
    assert all(c.request.headers["X-Internal-Key"] == "secret" for c in route.calls)


@respx.mock
async def test_client_error_is_not_retried():
    route = respx.post(URL).mock(return_value=httpx.Response(401))
    with pytest.raises(ToolError, match="401"):
        await n8n_client.call_tool("create-ticket", PAYLOAD)
    assert route.call_count == 1


@respx.mock
async def test_gives_up_after_bounded_retries_on_timeout():
    route = respx.post(URL).mock(side_effect=httpx.ReadTimeout("slow"))
    with pytest.raises(ToolError, match="unreachable"):
        await n8n_client.call_tool("create-ticket", PAYLOAD)
    assert route.call_count == 3  # 1 + n8n_retries


@respx.mock
async def test_agent_tool_end_to_end_through_mocked_n8n(ctx, monkeypatch):
    from app.agent import tools

    respx.post(URL).mock(return_value=httpx.Response(200, json={"ticket_id": "TK2002", "status": "open"}))
    c = ctx()
    res = await tools.dispatch("create_ticket", json.dumps({"category": "complaint",
                                                            "summary": "Giao hàng trễ 5 ngày"}), c)
    assert res["ticket_id"] == "TK2002" and c.actions == ["ticket_created"]
