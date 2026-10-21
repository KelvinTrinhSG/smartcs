import logging
import time
import uuid
from contextlib import asynccontextmanager

import httpx
from fastapi import Depends, FastAPI, HTTPException, Request

from app.agent import pipeline
from app.agent.tools import AgentContext
from app.core.auth import require_internal_key
from app.core.config import get_settings
from app.core.ratelimit import RateLimiter
from app.db.repo import Repo
from app.rag import ingest, loader
from app.schemas import (
    ChatMeta,
    ChatRequest,
    ChatResponse,
    IngestRequest,
    IngestResponse,
    VerifyRequest,
    VerifyResponse,
)

logger = logging.getLogger("smartcs")

MAX_INGEST_BYTES = 10 * 1024 * 1024
RATE_LIMITED_ANSWER = "Bạn đang gửi tin nhắn hơi nhanh. Vui lòng đợi một chút rồi thử lại nhé."


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    app.state.repo = None
    app.state.limiter = None
    if settings.redis_url:
        app.state.limiter = RateLimiter.from_url(
            settings.redis_url, settings.rate_limit_per_minute, settings.rate_limit_per_day
        )
    if settings.database_url:
        try:
            app.state.repo = await Repo.connect(settings.database_url)
        except Exception:  # noqa: BLE001 - run without memory/orders rather than not at all
            logger.exception("database unavailable; history and order lookup disabled")
    yield
    if app.state.repo:
        await app.state.repo.close()
    if app.state.limiter:
        await app.state.limiter.close()


app = FastAPI(title="SmartCS API", version="0.4.0", lifespan=lifespan)


def get_repo(request: Request) -> Repo | None:
    return getattr(request.app.state, "repo", None)


def get_limiter(request: Request) -> RateLimiter | None:
    return getattr(request.app.state, "limiter", None)


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok"}


@app.post("/v1/chat", response_model=ChatResponse, dependencies=[Depends(require_internal_key)])
async def chat(
    req: ChatRequest,
    repo: Repo | None = Depends(get_repo),
    limiter: RateLimiter | None = Depends(get_limiter),
) -> ChatResponse:
    started = time.perf_counter()
    settings = get_settings()
    if limiter and not await limiter.allow(req.user.id):
        # Checked before any LLM call, so flooding the bot costs nothing.
        return ChatResponse(answer=RATE_LIMITED_ANSWER, action="rate_limited", meta=ChatMeta(model="none"))

    ctx = AgentContext(
        session_id=req.session_id, channel=req.channel, user_id=req.user.id,
        turn_id=uuid.uuid4().hex[:12], repo=repo,
    )
    history: list[dict] = []
    if repo:
        try:
            ctx.phone = await repo.get_verified_phone(req.user.id)
            history = await repo.load_history(req.session_id, settings.history_messages)
        except Exception:  # noqa: BLE001
            logger.exception("could not load session state session=%s", req.session_id)

    try:
        turn = await pipeline.handle(req.message, ctx, history)
    except Exception as err:  # noqa: BLE001
        logger.exception("agent failed session=%s", req.session_id)
        raise HTTPException(status_code=502, detail="llm unavailable") from err

    out = turn.out
    latency_ms = int((time.perf_counter() - started) * 1000)
    if repo:
        try:
            # Only PII-masked text is ever stored.
            await repo.save_turn(req.session_id, turn.masked_input, out.answer)
            await repo.log_usage(req.session_id, req.channel, out.model, ctx.usage.tokens_in,
                                 ctx.usage.tokens_out, ctx.usage.cost_usd, latency_ms)
        except Exception:  # noqa: BLE001
            logger.exception("could not persist turn session=%s", req.session_id)

    return ChatResponse(
        answer=out.answer,
        citations=out.citations,
        action=out.action,
        meta=ChatMeta(
            model=out.model,
            tokens_in=ctx.usage.tokens_in,
            tokens_out=ctx.usage.tokens_out,
            cost_usd=round(ctx.usage.cost_usd, 6),
            latency_ms=latency_ms,
            chunks_used=len(ctx.retrieved),
            steps=out.steps,
            tools=[t["tool"] for t in ctx.tool_log],
            grounding=out.grounding,
            blocked_by=turn.blocked_by,
            pii_masked=turn.pii_found,
        ),
    )


@app.post("/v1/verify", response_model=VerifyResponse, dependencies=[Depends(require_internal_key)])
async def verify(req: VerifyRequest, repo: Repo | None = Depends(get_repo)) -> VerifyResponse:
    if repo is None:
        raise HTTPException(status_code=503, detail="database unavailable")
    await repo.set_verified_phone(req.user_id, req.phone)
    return VerifyResponse(verified=True, phone_masked=req.phone[:2] + "*" * 6 + req.phone[-2:])


@app.post("/v1/ingest", response_model=IngestResponse, dependencies=[Depends(require_internal_key)])
async def ingest_doc(req: IngestRequest) -> IngestResponse:
    if req.content is not None:
        content = req.content.encode("utf-8")
    else:
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            resp = await client.get(str(req.file_url))
        if resp.status_code != 200:
            raise HTTPException(status_code=400, detail=f"download failed: HTTP {resp.status_code}")
        content = resp.content
    if len(content) > MAX_INGEST_BYTES:
        raise HTTPException(status_code=413, detail="document too large")

    try:
        doc = loader.parse(content, req.mime_type, doc_id=req.doc_id, title=req.title)
    except ValueError as err:
        raise HTTPException(status_code=415, detail=str(err)) from err

    chunks = await ingest.ingest_document(doc)
    return IngestResponse(doc_id=req.doc_id, chunks=chunks)
