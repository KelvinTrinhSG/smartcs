import json
from datetime import UTC, datetime

import pytest

from app.agent import tools
from app.agent.tools import TZ, AgentContext
from app.llm import client as llm
from app.rag import retriever
from app.rag.retriever import Candidate
from app.rag.store import Hit

FIXED_NOW = datetime(2026, 10, 21, 10, 0, tzinfo=TZ)

WARRANTY_HIT = Candidate(
    hit=Hit("policy_warranty#0", "policy_warranty", "Chính sách bảo hành — TechZone", "1. Thời hạn bảo hành",
            "Laptop: 12 tháng (riêng ASUS Vivobook: 24 tháng).", 0.8),
    dense_score=0.8,
    rrf_score=0.03,
)


class FakeRepo:
    def __init__(self, phone_by_user=None, orders_by_phone=None):
        self.phone_by_user = phone_by_user or {}
        self.orders_by_phone = orders_by_phone or {}
        self.turns = []

    async def get_verified_phone(self, user_id):
        return self.phone_by_user.get(user_id)

    async def set_verified_phone(self, user_id, phone):
        self.phone_by_user[user_id] = phone

    async def get_orders(self, phone, order_id=None):
        orders = self.orders_by_phone.get(phone, [])
        return [o for o in orders if order_id is None or o["order_id"] == order_id]

    async def load_history(self, session_id, limit):
        return []

    async def save_turn(self, session_id, user_msg, assistant_msg):
        self.turns.append((session_id, user_msg, assistant_msg))

    async def log_usage(self, *args, **kwargs):
        pass


def order(order_id="TZ10001", status="delivered", delivered=datetime(2026, 7, 21, 3, 0, tzinfo=UTC)):
    return {
        "order_id": order_id, "status": status, "total_vnd": 15990000,
        "created_at": datetime(2026, 7, 18, 3, 0, tzinfo=UTC), "delivered_at": delivered,
        "items": json.dumps([{"sku": "LT-ASUS-VB15", "name": "Laptop ASUS Vivobook 15", "qty": 1,
                              "warranty_months": 24}]),
    }


def tool_call(name, args, id_="call_1"):
    return {"id": id_, "name": name, "arguments": json.dumps(args, ensure_ascii=False)}


class ScriptedLLM:
    """Replays a fixed list of LLM turns and records the messages it was sent."""

    def __init__(self, turns):
        self.turns = list(turns)
        self.calls = []

    async def __call__(self, messages, model=None, **kwargs):
        self.calls.append([dict(m) for m in messages])
        turn = self.turns.pop(0)
        if isinstance(turn, list):
            return llm.LLMResult("", "fake", 10, 2, 0.0001, tool_calls=turn)
        return llm.LLMResult(json.dumps(turn, ensure_ascii=False), "fake", 10, 5, 0.0001)


@pytest.fixture(autouse=True)
def fixed_now(monkeypatch):
    monkeypatch.setattr(tools, "now", lambda: FIXED_NOW)


@pytest.fixture(autouse=True)
def empty_kb(monkeypatch):
    """Never touch Qdrant in tests; the agent's KB prefetch finds nothing unless fake_retrieve is used."""
    queries = []

    async def _retrieve(query, usage=None, store=None):
        queries.append(query)
        return []

    monkeypatch.setattr(retriever, "retrieve", _retrieve)
    return queries


@pytest.fixture
def fake_retrieve(monkeypatch):
    queries = []

    async def _retrieve(query, usage=None, store=None):
        queries.append(query)
        return [WARRANTY_HIT]

    monkeypatch.setattr(retriever, "retrieve", _retrieve)
    return queries


@pytest.fixture
def script(monkeypatch):
    def _install(turns):
        s = ScriptedLLM(turns)
        monkeypatch.setattr(llm, "complete", s)
        return s

    return _install


@pytest.fixture
def ctx():
    def _make(**kw):
        base = {"session_id": "tg_42", "channel": "telegram", "user_id": "tg_42", "turn_id": "t1"}
        return AgentContext(**{**base, **kw})

    return _make
