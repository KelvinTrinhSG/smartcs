"""Calls n8n tool webhooks: shared-secret auth, timeout, bounded retries, idempotency key reuse."""

import asyncio
import logging
from typing import Any

import httpx

from app.core.config import get_settings

logger = logging.getLogger("smartcs.n8n")

RETRYABLE_STATUS = {502, 503, 504}


class ToolError(Exception):
    """n8n could not complete the action. The agent must not pretend it succeeded."""


async def call_tool(
    path: str, payload: dict[str, Any], *, client: httpx.AsyncClient | None = None
) -> dict[str, Any]:
    """POST {N8N_BASE_URL}/webhook/tool/<path>. The payload must already contain idempotency_key,
    so every retry is the same logical request and n8n can deduplicate it."""
    settings = get_settings()
    url = f"{settings.n8n_base_url.rstrip('/')}/webhook/tool/{path}"
    headers = {"X-Internal-Key": settings.internal_api_key}
    attempts = settings.n8n_retries + 1

    owns_client = client is None
    client = client or httpx.AsyncClient(timeout=settings.n8n_timeout_s)
    try:
        for attempt in range(1, attempts + 1):
            try:
                resp = await client.post(url, json=payload, headers=headers)
            except httpx.TransportError as err:  # timeouts, connection refused, ...
                logger.warning("n8n %s attempt %d/%d failed: %r", path, attempt, attempts, err)
                if attempt == attempts:
                    raise ToolError(f"n8n unreachable: {type(err).__name__}") from err
            else:
                if resp.status_code < 300:
                    return resp.json()
                if resp.status_code not in RETRYABLE_STATUS or attempt == attempts:
                    raise ToolError(f"n8n returned HTTP {resp.status_code}")
                logger.warning("n8n %s attempt %d/%d: HTTP %d", path, attempt, attempts, resp.status_code)
            await asyncio.sleep(settings.n8n_backoff_s * attempt)
    finally:
        if owns_client:
            await client.aclose()
    raise ToolError("unreachable")  # pragma: no cover
