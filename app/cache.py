"""
Response Cache
--------------
Caches GET responses in Redis with TTL-based expiry.

Features:
  - Per-endpoint configurable TTL
  - Cache invalidation on mutations (POST/PUT/DELETE)
  - In-flight request deduplication (stampede protection)
  - Cache key includes query params for correctness
  - Tracks hit/miss stats for metrics
"""

import json
import hashlib
import asyncio
from typing import Any
from app.redis_client import get_redis
from app.config import get_settings

settings = get_settings()

# TTL config per endpoint prefix (seconds)
ENDPOINT_TTL_MAP = {
    "/api/products": 60,
    "/api/users":    30,
    "/api/stats":    10,
    "/api/items":    45,
    "/health":       5,
}

# Lock TTL for stampede protection (seconds)
LOCK_TTL = 5


def _cache_key(endpoint: str, query_params: str) -> str:
    raw = f"{endpoint}?{query_params}" if query_params else endpoint
    hashed = hashlib.sha256(raw.encode()).hexdigest()[:16]
    return f"cache:{hashed}:{raw[:80]}"   # human-readable + unique


def _lock_key(cache_key: str) -> str:
    return f"lock:{cache_key}"


def _get_ttl(endpoint: str) -> int:
    for prefix, ttl in ENDPOINT_TTL_MAP.items():
        if endpoint.startswith(prefix):
            return ttl
    return settings.DEFAULT_CACHE_TTL


class ResponseCache:

    async def get(self, endpoint: str, query_params: str = "") -> tuple[Any | None, bool]:
        """
        Returns (data, cache_hit).
        If a lock exists (another request is computing), waits briefly.
        """
        redis = await get_redis()
        key = _cache_key(endpoint, query_params)

        cached = await redis.get(key)
        if cached:
            await redis.incr("metrics:cache_hits")
            return json.loads(cached), True

        # Check if another coroutine is computing this response
        lock = await redis.get(_lock_key(key))
        if lock:
            # Wait up to LOCK_TTL for the result to appear
            for _ in range(LOCK_TTL * 10):
                await asyncio.sleep(0.1)
                cached = await redis.get(key)
                if cached:
                    await redis.incr("metrics:cache_hits")
                    return json.loads(cached), True

        await redis.incr("metrics:cache_misses")
        return None, False

    async def set(
        self,
        endpoint: str,
        query_params: str,
        data: Any,
        ttl: int = None,
    ) -> None:
        redis = await get_redis()
        key = _cache_key(endpoint, query_params)
        ttl = ttl or _get_ttl(endpoint)
        await redis.setex(key, ttl, json.dumps(data))
        # Release lock if it was held
        await redis.delete(_lock_key(key))

    async def acquire_lock(self, endpoint: str, query_params: str) -> bool:
        """Lock so parallel identical requests don't all hit the DB."""
        redis = await get_redis()
        key = _lock_key(_cache_key(endpoint, query_params))
        return bool(await redis.set(key, "1", nx=True, ex=LOCK_TTL))

    async def invalidate(self, pattern: str) -> int:
        """
        Invalidate all cache keys matching a pattern.
        Called automatically on POST/PUT/DELETE.
        e.g. invalidate("/api/products") clears all product cache entries.
        """
        redis = await get_redis()
        keys = await redis.keys(f"cache:*{pattern}*")
        if keys:
            return await redis.delete(*keys)
        return 0

    async def invalidate_exact(self, endpoint: str, query_params: str = "") -> bool:
        redis = await get_redis()
        key = _cache_key(endpoint, query_params)
        return bool(await redis.delete(key))

    async def stats(self) -> dict:
        redis = await get_redis()
        hits = int(await redis.get("metrics:cache_hits") or 0)
        misses = int(await redis.get("metrics:cache_misses") or 0)
        total = hits + misses
        keys = await redis.keys("cache:*")
        return {
            "total_cached_keys": len(keys),
            "hits": hits,
            "misses": misses,
            "hit_ratio": round(hits / total, 4) if total else 0.0,
        }


# Singleton
cache = ResponseCache()
