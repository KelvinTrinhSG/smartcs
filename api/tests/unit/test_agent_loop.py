import pytest

from app.agent import loop, n8n_client
from app.core.config import get_settings
from tests.conftest import FakeRepo, order, tool_call


async def test_kb_is_prefetched_with_the_customers_own_words(ctx, script, fake_retrieve):
    s = script([
        {"answer": "ASUS Vivobook được bảo hành 24 tháng.", "citations": ["policy_warranty#0", "made_up#1"]},
    ])
    out = await loop.run("ASUS bảo hành bao lâu?", ctx())
    assert fake_retrieve == ["ASUS bảo hành bao lâu?"]
    assert out.answer.startswith("ASUS Vivobook")
    assert [c.chunk_id for c in out.citations] == ["policy_warranty#0"]  # hallucinated id dropped
    assert out.steps == 1 and out.action == "none"
    first_call = s.calls[0]
    assert first_call[-1]["role"] == "tool" and "ASUS Vivobook: 24" in first_call[-1]["content"]
    assert first_call[-2]["tool_calls"][0]["function"]["name"] == "search_kb"


async def test_model_can_search_again_with_its_own_query(ctx, script, fake_retrieve):
    script([
        [tool_call("search_kb", {"query": "thời hạn bảo hành laptop"})],
        {"answer": "24 tháng.", "citations": ["policy_warranty#0"]},
    ])
    out = await loop.run("ASUS thì sao?", ctx())
    assert fake_retrieve == ["ASUS thì sao?", "thời hạn bảo hành laptop"]
    assert out.steps == 2


async def test_order_question_without_phone_requests_verification(ctx, script):
    # The model answers directly without calling any tool; the prefetch still guarantees the action.
    script([{"answer": "Bạn vui lòng bấm nút chia sẻ số điện thoại nhé.", "citations": []}])
    c = ctx(repo=FakeRepo())
    out = await loop.run("Đơn TZ10002 của tôi đâu rồi?", c)
    assert out.action == "request_phone"
    expected = {"tool": "lookup_order", "args": {"order_id": "TZ10002"}, "ok": False, "auto": True}
    assert c.tool_log[1] == expected


@pytest.mark.parametrize("q, expected", [
    ("Đơn hàng của tôi thế nào rồi?", {}),
    ("kiểm tra giúp tz10003", {"order_id": "TZ10003"}),
    ("don hang cua minh giao chua", {}),
    ("Cho tôi xem mã đơn", {}),
    ("Check my order.", {}),
    ("What's the order status?", {}),
    ("How do I place an order?", None),
    ("Laptop ASUS bảo hành bao lâu?", None),
    ("Thủ tục đơn giản không?", None),
])
def test_order_intent(q, expected):
    assert loop.order_intent(q) == expected


async def test_ticket_flow_reports_ticket_created(ctx, script, monkeypatch):
    async def fake_call(path, payload, **kw):
        return {"ticket_id": "TK1001", "status": "open"}

    monkeypatch.setattr(n8n_client, "call_tool", fake_call)
    phone = "0901234567"
    script([
        [tool_call("create_ticket", {"category": "warranty", "summary": "Laptop ASUS lỗi màn hình",
                                     "order_id": "TZ10001"}, "c2")],
        {"answer": "Mình đã tạo phiếu TK1001 cho bạn.", "citations": []},
    ])
    c = ctx(phone=phone, repo=FakeRepo(orders_by_phone={phone: [order()]}))
    out = await loop.run("Laptop đơn TZ10001 bị lỗi màn hình, tạo phiếu bảo hành giúp tôi", c)
    assert out.action == "ticket_created"
    assert [t["tool"] for t in c.tool_log] == ["search_kb", "lookup_order", "create_ticket"]
    assert [t.get("auto", False) for t in c.tool_log] == [True, True, False]


async def test_invalid_arguments_are_fed_back_to_the_model(ctx, script):
    s = script([
        [tool_call("book_appointment", {"store_id": "TZ-HN01", "start_time": "2026-10-22T14:15",
                                        "purpose": "bảo hành"})],
        {"answer": "Khung giờ phải là phút 00 hoặc 30, bạn chọn 14:00 hay 14:30?", "citations": []},
    ])
    out = await loop.run("Đặt lịch 14h15 mai ở Hà Nội", ctx(dry_run=True))
    assert out.action == "none"
    assert "invalid_arguments" in s.calls[1][-1]["content"]


async def test_step_limit_falls_back_safely(ctx, script, fake_retrieve):
    n = get_settings().agent_max_steps
    script([[tool_call("search_kb", {"query": "lặp vô hạn"}, f"c{i}")] for i in range(n)])
    out = await loop.run("?", ctx())
    assert out.answer == loop.FALLBACK and out.steps == n


async def test_non_json_final_answer_is_returned_as_text(ctx, monkeypatch):
    from app.llm import client as llm

    async def raw(messages, model=None, **kw):
        return llm.LLMResult("Xin chào!", "fake", 1, 1, 0.0)

    monkeypatch.setattr(llm, "complete", raw)
    out = await loop.run("hi", ctx())
    assert out.answer == "Xin chào!" and out.citations == []


async def test_system_prompt_contains_time_and_identity(ctx, script):
    s = script([{"answer": "Chào bạn!", "citations": []}, {"answer": "Chào bạn!", "citations": []}])
    await loop.run("Xin chào", ctx())
    system = s.calls[0][0]["content"]
    assert "21/10/2026 10:00" in system and "ngày mai là Thứ Năm, 22/10/2026" in system
    verified_line = "Khách hàng: đã xác minh số điện thoại"
    assert verified_line not in system and "chưa xác minh" not in system  # see prompts.py
    await loop.run("Xin chào", ctx(phone="0901234567"))
    assert verified_line in s.calls[1][0]["content"]
