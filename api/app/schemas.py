import re
from typing import Literal

from pydantic import BaseModel, Field, HttpUrl, field_validator, model_validator

Action = Literal["none", "handoff", "ticket_created", "appointment_booked", "request_phone", "blocked",
                 "rate_limited"]


class ChatUser(BaseModel):
    id: str = Field(min_length=1, max_length=64)


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
    steps: int = 0
    tools: list[str] = []
    grounding: str = "skipped"
    blocked_by: str = ""
    pii_masked: dict[str, int] = {}


class ChatResponse(BaseModel):
    answer: str
    citations: list[Citation] = []
    action: Action = "none"
    meta: ChatMeta


class VerifyRequest(BaseModel):
    """Sent by n8n only when a Telegram contact was shared by its owner (contact.user_id == from.id)."""

    user_id: str = Field(pattern=r"^tg_\d+$")
    phone: str

    @field_validator("phone")
    @classmethod
    def _vn_mobile(cls, v: str) -> str:
        digits = re.sub(r"\D", "", v)
        if digits.startswith("84"):
            digits = "0" + digits[2:]
        if not re.fullmatch(r"0\d{9}", digits):
            raise ValueError("not a Vietnamese mobile number")
        return digits


class VerifyResponse(BaseModel):
    verified: bool
    phone_masked: str


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
