"""Fixed-window rate limit per user in Redis (per minute and per day). Fails open if Redis is down."""

import logging
import time

from redis import asyncio as aioredis

logger = logging.getLogger("smartcs.ratelimit")


class RateLimiter:
    def __init__(self, redis: aioredis.Redis, per_minute: int, per_day: int):
        self.redis = redis
        self.limits = ((60, per_minute), (86400, per_day))

    @classmethod
    def from_url(cls, url: str, per_minute: int, per_day: int) -> "RateLimiter":
        return cls(aioredis.from_url(url), per_minute, per_day)

    async def allow(self, user_id: str) -> bool:
        now = int(time.time())
        try:
            pipe = self.redis.pipeline()
            for window, _ in self.limits:
                key = f"rl:{user_id}:{window}:{now // window}"
                pipe.incr(key)
                pipe.expire(key, window)
            results = await pipe.execute()
        except Exception:  # noqa: BLE001
            logger.exception("rate limiter unavailable, allowing request")
            return True
        counts = results[0::2]
        return all(c <= limit for c, (_, limit) in zip(counts, self.limits, strict=True))

    async def close(self) -> None:
        await self.redis.aclose()
