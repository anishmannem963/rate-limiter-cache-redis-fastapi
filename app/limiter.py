"""
Token Bucket Rate Limiter
-------------------------
Each client gets a "bucket" with a max capacity of tokens.
- Tokens refill at a steady rate over time.
- Each request consumes 1 token.
- If bucket is empty → 429 Too Many Requests.

Why token bucket over fixed window?
  Fixed window allows 2x burst at window boundaries.
  Token bucket smooths traffic and allows controlled short bursts.

Redis Lua script ensures atomicity — no race conditions under high concurrency.
"""

import time
from dataclasses import dataclass
from app.redis_client import get_redis
from app.config import get_settings

settings = get_settings()

# Atomic Lua script: read → calculate → write in one Redis transaction
TOKEN_BUCKET_SCRIPT = """
local key        = KEYS[1]
local capacity   = tonumber(ARGV[1])
local refill_rate= tonumber(ARGV[2])  -- tokens per second
local now        = tonumber(ARGV[3])
local requested  = tonumber(ARGV[4])

local data = redis.call('HMGET', key, 'tokens', 'last_refill')
local tokens      = tonumber(data[1]) or capacity
local last_refill = tonumber(data[2]) or now

-- Refill tokens based on elapsed time
local elapsed = math.max(0, now - last_refill)
local new_tokens = math.min(capacity, tokens + elapsed * refill_rate)

if new_tokens >= requested then
    new_tokens = new_tokens - requested
    redis.call('HMSET', key, 'tokens', new_tokens, 'last_refill', now)
    redis.call('EXPIRE', key, math.ceil(capacity / refill_rate) * 2)
    return {1, math.floor(new_tokens), 0}   -- allowed, remaining, retry_after
else
    -- Calculate how long until enough tokens refill
    local deficit      = requested - new_tokens
    local retry_after  = math.ceil(deficit / refill_rate)
    redis.call('HMSET', key, 'tokens', new_tokens, 'last_refill', now)
    redis.call('EXPIRE', key, math.ceil(capacity / refill_rate) * 2)
    return {0, 0, retry_after}              -- denied, remaining, retry_after
end
"""


@dataclass
class RateLimitResult:
    allowed: bool
    remaining: int
    retry_after: int       # seconds until retry if denied
    limit: int
    window_seconds: int


class TokenBucketLimiter:
    def __init__(self):
        self._script_sha: str | None = None

    async def _load_script(self, redis) -> str:
        """Load Lua script into Redis once, reuse SHA for efficiency."""
        if self._script_sha is None:
            self._script_sha = await redis.script_load(TOKEN_BUCKET_SCRIPT)
        return self._script_sha

    def _bucket_key(self, identifier: str, endpoint: str) -> str:
        """Separate bucket per client per endpoint for fine-grained control."""
        return f"rl:bucket:{identifier}:{endpoint}"

    async def check(
        self,
        identifier: str,
        endpoint: str,
        limit: int = None,
        window_seconds: int = None,
    ) -> RateLimitResult:
        limit = limit or settings.DEFAULT_RATE_LIMIT
        window_seconds = window_seconds or settings.DEFAULT_WINDOW_SECONDS

        capacity = int(limit * settings.BURST_MULTIPLIER)
        refill_rate = limit / window_seconds   # tokens per second

        redis = await get_redis()
        sha = await self._load_script(redis)
        key = self._bucket_key(identifier, endpoint)
        now = time.time()

        try:
            result = await redis.evalsha(
                sha, 1, key,
                capacity, refill_rate, now, 1
            )
            allowed, remaining, retry_after = int(result[0]), int(result[1]), int(result[2])
            return RateLimitResult(
                allowed=bool(allowed),
                remaining=remaining,
                retry_after=retry_after,
                limit=limit,
                window_seconds=window_seconds,
            )
        except Exception:
            # Fail open — don't block traffic if Redis is temporarily down
            return RateLimitResult(
                allowed=True,
                remaining=limit,
                retry_after=0,
                limit=limit,
                window_seconds=window_seconds,
            )

    async def get_bucket_state(self, identifier: str, endpoint: str) -> dict:
        """Inspect a bucket's current state — useful for debugging."""
        redis = await get_redis()
        key = self._bucket_key(identifier, endpoint)
        data = await redis.hgetall(key)
        return {
            "key": key,
            "tokens": float(data.get("tokens", 0)),
            "last_refill": float(data.get("last_refill", 0)),
        }

    async def reset_bucket(self, identifier: str, endpoint: str) -> bool:
        """Manually reset a client's bucket — admin use."""
        redis = await get_redis()
        key = self._bucket_key(identifier, endpoint)
        return bool(await redis.delete(key))


# Singleton
limiter = TokenBucketLimiter()
