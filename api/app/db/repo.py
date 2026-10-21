"""All SQL the API runs. The agent only reaches the DB through these methods."""

from datetime import date, datetime
from typing import Any

import asyncpg

ORDERS_SQL = """
SELECT o.order_id, o.status, o.total_vnd, o.created_at, o.delivered_at,
       json_agg(json_build_object('sku', p.sku, 'name', p.name, 'qty', i.qty,
                                  'warranty_months', p.warranty_months) ORDER BY p.sku) AS items
FROM orders o
JOIN customers c ON c.id = o.customer_id
JOIN order_items i ON i.order_id = o.order_id
JOIN products p ON p.sku = i.sku
WHERE c.phone = $1 AND ($2::text IS NULL OR o.order_id = $2)
GROUP BY o.order_id
ORDER BY o.created_at DESC
LIMIT 10
"""


COST_SQL = """
SELECT count(*)                                             AS turns,
       count(DISTINCT session_id)                           AS sessions,
       coalesce(sum(cost_usd), 0)::float                    AS cost_usd,
       coalesce(sum(tokens_in), 0)                          AS tokens_in,
       coalesce(sum(tokens_out), 0)                         AS tokens_out,
       coalesce(sum(cached_tokens), 0)                      AS cached_tokens,
       coalesce(avg(cache_hit::int), 0)::float              AS cache_hit_rate,
       coalesce(percentile_cont(0.5) WITHIN GROUP (ORDER BY latency_ms), 0)::int  AS latency_p50_ms,
       coalesce(percentile_cont(0.95) WITHIN GROUP (ORDER BY latency_ms), 0)::int AS latency_p95_ms
FROM usage_logs
WHERE (created_at AT TIME ZONE 'Asia/Ho_Chi_Minh')::date = $1
"""


class Repo:
    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool

    @classmethod
    async def connect(cls, dsn: str) -> "Repo":
        return cls(await asyncpg.create_pool(dsn, min_size=1, max_size=5))

    async def close(self) -> None:
        await self.pool.close()

    async def get_verified_phone(self, user_id: str) -> str | None:
        return await self.pool.fetchval("SELECT phone FROM verified_users WHERE user_id = $1", user_id)

    async def set_verified_phone(self, user_id: str, phone: str) -> None:
        await self.pool.execute(
            """INSERT INTO verified_users (user_id, phone) VALUES ($1, $2)
               ON CONFLICT (user_id) DO UPDATE SET phone = EXCLUDED.phone, verified_at = now()""",
            user_id,
            phone,
        )

    async def get_orders(self, phone: str, order_id: str | None = None) -> list[dict[str, Any]]:
        rows = await self.pool.fetch(ORDERS_SQL, phone, order_id)
        return [dict(r) for r in rows]

    async def load_history(self, session_id: str, limit: int) -> list[dict[str, str]]:
        rows = await self.pool.fetch(
            "SELECT role, content FROM messages WHERE session_id = $1 ORDER BY id DESC LIMIT $2",
            session_id,
            limit,
        )
        return [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]

    async def save_turn(self, session_id: str, user_msg: str, assistant_msg: str) -> None:
        await self.pool.executemany(
            "INSERT INTO messages (session_id, role, content) VALUES ($1, $2, $3)",
            [(session_id, "user", user_msg), (session_id, "assistant", assistant_msg)],
        )

    async def log_usage(
        self, session_id: str, channel: str, model: str, tokens_in: int, tokens_out: int,
        cost_usd: float, latency_ms: int, *, route: str = "small", cache_hit: bool = False,
        cached_tokens: int = 0, llm_calls: int = 0, created_at: datetime | None = None,
    ) -> None:
        await self.pool.execute(
            """INSERT INTO usage_logs
                   (session_id, channel, model, tokens_in, tokens_out, cost_usd, latency_ms, route, cache_hit,
                    cached_tokens, llm_calls, created_at)
               VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, COALESCE($12, now()))""",
            session_id, channel, model, tokens_in, tokens_out, cost_usd, latency_ms, route, cache_hit,
            cached_tokens, llm_calls, created_at,
        )

    async def cost_report(self, day: date) -> dict[str, Any]:
        """Totals for one calendar day in Vietnam time (WF-30 daily report, WF-31 budget alert)."""
        row = await self.pool.fetchrow(COST_SQL, day)
        routes = await self.pool.fetch(
            """SELECT route, count(*) AS n FROM usage_logs
               WHERE (created_at AT TIME ZONE 'Asia/Ho_Chi_Minh')::date = $1
               GROUP BY route ORDER BY n DESC""",
            day,
        )
        out = dict(row) if row else {}
        out["routes"] = {r["route"]: r["n"] for r in routes}
        return out
