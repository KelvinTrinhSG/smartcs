import pytest

from app.agent import pipeline, prompts
from app.cache import semantic
from app.llm import client as llm
from tests.conftest import FIXED_NOW, FakeRepo, tool_call


def test_agent_prompt_prefix_is_identical_across_requests():
    """OpenAI prompt caching needs a byte-identical prefix: time/identity/channel must come last."""
    a = prompts.agent_prompt("telegram", FIXED_NOW, phone_verified=False)
    b = prompts.agent_prompt("voice", FIXED_NOW.replace(hour=17, minute=42), phone_verified=True)
    marker = "Phiên hiện tại:"
    static_a, static_b = a[: a.index(marker)], b[: b.index(marker)]
    assert static_a == static_b and a != b
    assert len(static_a) > 2000  # long enough to be worth caching


@pytest.mark.parametrize("q, ok", [
    ("Laptop ASUS bảo hành bao lâu?", True),
    ("Nó còn bảo hành không?", False),
    ("Vậy còn cái kia thì sao?", False),
    ("Sản phẩm đó đổi trả được không?", False),
])
def test_contextual_questions_are_not_cached(q, ok):
    assert semantic.cacheable_question(q) is ok


@pytest.fixture
def cache_spy(monkeypatch, llm_guards_off):
    monkeypatch.setattr(llm_guards_off, "semantic_cache", True)
    calls = {"lookup": [], "store": []}

    async def lookup(question, channel, usage=None):
        calls["lookup"].append(question)
        return calls.get("hit")

    async def store(question, channel, answer, citations):
        calls["store"].append((question, answer))

    monkeypatch.setattr(semantic, "lookup", lookup)
    monkeypatch.setattr(semantic, "store", store)
    return calls


async def test_cache_hit_skips_the_agent(ctx, script, cache_spy):
    cite = {"doc_id": "policy_warranty", "chunk_id": "policy_warranty#0"}
    cache_spy["hit"] = semantic.CacheHit("24 tháng.", [cite], 0.97, "ASUS bảo hành bao lâu?")
    s = script([])
    turn = await pipeline.handle("Laptop ASUS bảo hành mấy tháng?", ctx(), [])
    assert turn.route == "cache" and turn.out.answer == "24 tháng." and s.calls == []


async def test_kb_answer_is_stored(ctx, script, cache_spy, fake_retrieve):
    script([{"answer": "24 tháng.", "citations": ["policy_warranty#0"]}])
    await pipeline.handle("Laptop ASUS bảo hành bao lâu?", ctx(), [])
    assert cache_spy["store"] == [("Laptop ASUS bảo hành bao lâu?", "24 tháng.")]


KB_ANSWER = {"answer": "24 tháng.", "citations": ["policy_warranty#0"]}
TICKET = tool_call("create_ticket", {"category": "warranty", "summary": "Laptop lỗi màn hình"})


@pytest.mark.parametrize("message, turns", [
    ("Số tôi là 0901234567, ASUS bảo hành bao lâu?", [KB_ANSWER]),       # PII in the question
    ("Đơn TZ10001 bảo hành bao lâu?", [KB_ANSWER]),                      # about a personal order
    ("Tạo phiếu bảo hành giúp tôi", [[TICKET], KB_ANSWER]),              # side effect happened
    ("Xin chào", [{"answer": "Chào bạn!", "citations": []}]),            # not a KB answer
])
async def test_personal_or_action_turns_are_never_cached(ctx, script, cache_spy, fake_retrieve, message,
                                                         turns):
    script(turns)
    await pipeline.handle(message, ctx(dry_run=True, repo=FakeRepo()), [])
    assert cache_spy["store"] == []


async def test_router_sends_complex_turns_to_the_large_model(ctx, script, llm_guards_off, monkeypatch):
    monkeypatch.setattr(llm_guards_off, "injection_classifier", True)
    s = script([{"label": "ok", "complexity": "complex", "reason": "khiếu nại"},
                {"answer": "Mình rất tiếc…", "citations": []}])
    models = []
    orig = llm.complete

    async def spy(messages, model=None, **kw):
        models.append(model)
        return await orig(messages, model, **kw)

    monkeypatch.setattr(llm, "complete", spy)
    turn = await pipeline.handle("Giao trễ 5 ngày, máy lại trầy, tôi rất bực!", ctx(), [])
    assert turn.route == "large" and models[-1] == llm_guards_off.llm_model_large
    assert len(s.calls) == 2
