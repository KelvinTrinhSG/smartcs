import logging
import time

import httpx
from fastapi import Depends, FastAPI, HTTPException

from app.agent import answer
from app.core.auth import require_internal_key
from app.llm.cost import Usage
from app.rag import ingest, loader, retriever
from app.schemas import ChatMeta, ChatRequest, ChatResponse, IngestRequest, IngestResponse

logger = logging.getLogger("smartcs")

MAX_INGEST_BYTES = 10 * 1024 * 1024

app = FastAPI(title="SmartCS API", version="0.2.0")


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok"}


@app.post("/v1/chat", response_model=ChatResponse, dependencies=[Depends(require_internal_key)])
async def chat(req: ChatRequest) -> ChatResponse:
    started = time.perf_counter()
    usage = Usage()

    try:
        context = await retriever.retrieve(req.message, usage=usage)
    except Exception:  # noqa: BLE001 - degrade to "no context" instead of failing the chat
        logger.exception("retrieval failed session=%s", req.session_id)
        context = []

    try:
        out = await answer.generate(req.message, req.channel, context, usage)
    except Exception as err:  # noqa: BLE001
        logger.exception("llm call failed session=%s", req.session_id)
        raise HTTPException(status_code=502, detail="llm unavailable") from err

    return ChatResponse(
        answer=out.answer,
        citations=out.citations,
        action="handoff" if out.needs_handoff else "none",
        meta=ChatMeta(
            model=out.model,
            tokens_in=usage.tokens_in,
            tokens_out=usage.tokens_out,
            cost_usd=round(usage.cost_usd, 6),
            latency_ms=int((time.perf_counter() - started) * 1000),
            chunks_used=len(context),
        ),
    )


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
