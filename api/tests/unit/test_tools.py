import json
from datetime import UTC, datetime

import pytest

from app.agent import n8n_client, tools
from app.agent.n8n_client import ToolError
from tests.conftest import FakeRepo, order

PHONE = "0901234567"


async def call(name, args, c):
    return await tools.dispatch(name, json.dumps(args), c)


@pytest.mark.parametrize(
    "start, ok",
    [
        ("2026-10-22T14:30", True),     # tomorrow afternoon
        ("2026-10-21T10:30", False),    # less than 1h ahead
        ("2026-10-20T14:00", False),    # past
        ("2026-12-01T14:00", False),    # > 30 days
        ("2026-10-22T07:30", False),    # before opening
        ("2026-10-22T21:30", False),    # after last slot
        ("2026-10-22T14:15", False),    # not :00/:30
        ("2026-10-22T21:00", True),     # last slot
    ],
)
async def test_book_appointment_business_rules(ctx, start, ok):
    c = ctx(dry_run=True)
    args = {"store_id": "TZ-HN01", "start_time": start, "purpose": "bảo hành"}
    res = await call("book_appointment", args, c)
    assert ("error" not in res) is ok, res
    assert ("appointment_booked" in c.actions) is ok


async def test_unknown_store_rejected(ctx):
    res = await call("book_appointment", {"store_id": "TZ-DN01", "start_time": "2026-10-22T14:00",
                                          "purpose": "x x x"}, ctx(dry_run=True))
    assert res["error"] == "invalid_arguments"


async def test_lookup_order_requires_verified_phone(ctx):
    c = ctx(repo=FakeRepo())
    res = await call("lookup_order", {}, c)
    assert res["error"] == "phone_not_verified"
    assert c.actions == ["request_phone"]


async def test_lookup_order_returns_warranty_end_date(ctx):
    c = ctx(phone=PHONE, repo=FakeRepo(orders_by_phone={PHONE: [order()]}))
    res = await call("lookup_order", {"order_id": "tz10001"}, c)  # normalised to TZ10001
    item = res["orders"][0]["items"][0]
    assert res["orders"][0]["delivered_on"] == "2026-07-21"
    assert item["warranty_until"] == "2028-07-21"
    assert item["warranty_status"] == "ACTIVE, 639 days left"
    assert res["order_count"] == 1


async def test_expired_and_undelivered_warranty_status(ctx):
    expired = order("TZ10005", delivered=datetime(2024, 8, 15, 3, 0, tzinfo=UTC))  # 24 months -> 2026-08-15
    shipping = order("TZ10006", status="shipping", delivered=None)
    c = ctx(phone=PHONE, repo=FakeRepo(orders_by_phone={PHONE: [expired, shipping]}))
    res = await call("lookup_order", {}, c)
    statuses = [o["items"][0]["warranty_status"] for o in res["orders"]]
    assert statuses == ["EXPIRED 67 days ago", "not started (order not delivered yet)"]
    assert res["order_count"] == 2


async def test_lookup_other_customers_order_reveals_nothing(ctx):
    repo = FakeRepo(orders_by_phone={"0999999999": [order("TZ10009")]})
    res = await call("lookup_order", {"order_id": "TZ10009"}, ctx(phone=PHONE, repo=repo))
    assert res["orders"] == []


async def test_lookup_order_rejects_malformed_id(ctx):
    res = await call("lookup_order", {"order_id": "1; DROP TABLE orders"}, ctx(phone=PHONE, repo=FakeRepo()))
    assert res["error"] == "invalid_arguments"


async def test_create_ticket_for_foreign_order_is_refused(ctx, monkeypatch):
    async def boom(*a, **k):
        raise AssertionError("n8n must not be called")

    monkeypatch.setattr(n8n_client, "call_tool", boom)
    res = await call("create_ticket", {"category": "warranty", "summary": "Màn hình bị sọc ngang",
                                       "order_id": "TZ10009"}, ctx(phone=PHONE, repo=FakeRepo()))
    assert res["error"] == "order_not_found"


async def test_create_ticket_sends_idempotency_key(ctx, monkeypatch):
    sent = {}

    async def fake_call(path, payload, **kw):
        sent.update(path=path, payload=payload)
        return {"ticket_id": "TK1001", "status": "open"}

    monkeypatch.setattr(n8n_client, "call_tool", fake_call)
    c = ctx(phone=PHONE, repo=FakeRepo(orders_by_phone={PHONE: [order()]}))
    res = await call("create_ticket", {"category": "warranty", "summary": "Laptop không lên nguồn",
                                       "order_id": "TZ10001"}, c)
    assert res == {"ticket_id": "TK1001", "status": "open"}
    assert sent["path"] == "create-ticket"
    assert sent["payload"]["idempotency_key"] == "tg_42:t1:create_ticket"
    assert sent["payload"]["customer_phone"] == PHONE
    assert c.actions == ["ticket_created"]


async def test_n8n_failure_becomes_tool_error_without_action(ctx, monkeypatch):
    async def down(*a, **k):
        raise ToolError("n8n unreachable")

    monkeypatch.setattr(n8n_client, "call_tool", down)
    c = ctx()
    args = {"reason": "customer_request", "summary": "Khách muốn gặp nhân viên"}
    res = await call("handoff_to_human", args, c)
    assert res["error"] == "tool_error"
    assert c.actions == []


async def test_slot_taken_is_reported(ctx, monkeypatch):
    async def taken(*a, **k):
        return {"event_id": "AP501", "result": "slot_taken"}

    monkeypatch.setattr(n8n_client, "call_tool", taken)
    c = ctx()
    res = await call("book_appointment", {"store_id": "TZ-HN01", "start_time": "2026-10-22T14:00",
                                          "purpose": "bảo hành"}, c)
    assert res["error"] == "slot_taken" and c.actions == []


async def test_unknown_tool(ctx):
    assert (await call("rm_rf", {}, ctx()))["error"] == "unknown_tool"


def test_tool_specs_are_openai_shaped():
    names = {s["function"]["name"] for s in tools.TOOL_SPECS}
    assert names == {"search_kb", "lookup_order", "create_ticket", "book_appointment", "handoff_to_human"}
    assert all(s["function"]["parameters"]["type"] == "object" for s in tools.TOOL_SPECS)
