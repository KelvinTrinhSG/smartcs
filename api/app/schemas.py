from typing import Literal

from pydantic import BaseModel, Field, HttpUrl, model_validator


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
    chunk_id: str
    title: str = ""
    section: str = ""


class ChatMeta(BaseModel):
    model: str
    cache_hit: bool = False
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0
    latency_ms: int = 0
    chunks_used: int = 0


class ChatResponse(BaseModel):
    answer: str
    citations: list[Citation] = []
    action: Literal["none", "handoff", "ticket_created"] = "none"
    meta: ChatMeta


class IngestRequest(BaseModel):
    doc_id: str = Field(pattern=r"^[A-Za-z0-9_\-]{1,64}$")
    title: str | None = None
    content: str | None = None
    file_url: HttpUrl | None = None
    mime_type: str = "text/markdown"

    @model_validator(mode="after")
    def _one_source(self) -> "IngestRequest":
        if (self.content is None) == (self.file_url is None):
            raise ValueError("provide exactly one of content or file_url")
        return self


class IngestResponse(BaseModel):
    doc_id: str
    chunks: int
