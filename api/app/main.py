import logging
import time

from fastapi import Depends, FastAPI, HTTPException

from app.agent.prompts import system_prompt
from app.core.auth import require_internal_key
from app.llm import client as llm
from app.schemas import ChatMeta, ChatRequest, ChatResponse

logger = logging.getLogger("smartcs")

app = FastAPI(title="SmartCS API", version="0.1.0")


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok"}


@app.post("/v1/chat", response_model=ChatResponse, dependencies=[Depends(require_internal_key)])
async def chat(req: ChatRequest) -> ChatResponse:
    # Week 1: plain LLM call. RAG, guardrails, routing and tools come in later weeks.
    started = time.perf_counter()
    messages = [
        {"role": "system", "content": system_prompt(req.channel)},
        {"role": "user", "content": req.message},
    ]
    try:
        result = await llm.complete(messages)
    except Exception as err:  # noqa: BLE001
        logger.exception("llm call failed session=%s", req.session_id)
        raise HTTPException(status_code=502, detail="llm unavailable") from err

    return ChatResponse(
        answer=result.text,
        meta=ChatMeta(
            model=result.model,
            tokens_in=result.tokens_in,
            tokens_out=result.tokens_out,
            cost_usd=result.cost_usd,
            latency_ms=int((time.perf_counter() - started) * 1000),
        ),
    )
