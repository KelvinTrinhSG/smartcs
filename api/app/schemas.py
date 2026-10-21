from typing import Literal

from pydantic import BaseModel, Field


class ChatUser(BaseModel):
    id: str
    phone_verified: str | None = None


class ChatRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=128)
    channel: Literal["telegram", "web", "voice"]
    user: ChatUser
    message: str = Field(min_length=1, max_length=4000)


class Citation(BaseModel):
    doc_id: str
    page: int | None = None


class ChatMeta(BaseModel):
    model: str
    cache_hit: bool = False
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0
    latency_ms: int = 0


class ChatResponse(BaseModel):
    answer: str
    citations: list[Citation] = []
    action: Literal["none", "handoff", "ticket_created"] = "none"
    meta: ChatMeta
