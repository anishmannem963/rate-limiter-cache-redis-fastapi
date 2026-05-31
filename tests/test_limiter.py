"""
Tests for the Token Bucket Rate Limiter.
Uses a mock Redis to avoid needing a real instance.
"""

import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.fixture
def mock_redis():
    redis = AsyncMock()
    redis.script_load = AsyncMock(return_value="mock_sha")
    return redis


@pytest.mark.asyncio
async def test_request_allowed(mock_redis):
    """First request should always be allowed."""
    mock_redis.evalsha = AsyncMock(return_value=[1, 99, 0])  # allowed, 99 remaining
    with patch("app.limiter.get_redis", return_value=mock_redis):
        from app.limiter import TokenBucketLimiter
        lb = TokenBucketLimiter()
        result = await lb.check("user_123", "/api/products", limit=100, window_seconds=60)
    assert result.allowed is True
    assert result.remaining == 99


@pytest.mark.asyncio
async def test_request_denied_when_exhausted(mock_redis):
    """Should deny when bucket is empty."""
    mock_redis.evalsha = AsyncMock(return_value=[0, 0, 5])   # denied, retry in 5s
    with patch("app.limiter.get_redis", return_value=mock_redis):
        from app.limiter import TokenBucketLimiter
        lb = TokenBucketLimiter()
        result = await lb.check("user_123", "/api/products", limit=100, window_seconds=60)
    assert result.allowed is False
    assert result.retry_after == 5
    assert result.remaining == 0


@pytest.mark.asyncio
async def test_fail_open_on_redis_error():
    """If Redis is down, requests should be allowed (fail open)."""
    broken_redis = AsyncMock()
    broken_redis.script_load = AsyncMock(side_effect=Exception("Redis down"))
    with patch("app.limiter.get_redis", return_value=broken_redis):
        from app.limiter import TokenBucketLimiter
        lb = TokenBucketLimiter()
        result = await lb.check("user_123", "/api/products")
    assert result.allowed is True   # fail open


@pytest.mark.asyncio
async def test_bucket_key_is_per_client_per_endpoint():
    """Different clients and endpoints should get separate buckets."""
    from app.limiter import TokenBucketLimiter
    lb = TokenBucketLimiter()
    key1 = lb._bucket_key("user_A", "/api/products")
    key2 = lb._bucket_key("user_B", "/api/products")
    key3 = lb._bucket_key("user_A", "/api/users")
    assert key1 != key2
    assert key1 != key3
    assert key2 != key3


@pytest.mark.asyncio
async def test_reset_bucket(mock_redis):
    mock_redis.delete = AsyncMock(return_value=1)
    with patch("app.limiter.get_redis", return_value=mock_redis):
        from app.limiter import TokenBucketLimiter
        lb = TokenBucketLimiter()
        result = await lb.reset_bucket("user_123", "/api/products")
    assert result is True


@pytest.mark.asyncio
async def test_rate_limit_result_fields(mock_redis):
    mock_redis.evalsha = AsyncMock(return_value=[1, 42, 0])
    with patch("app.limiter.get_redis", return_value=mock_redis):
        from app.limiter import TokenBucketLimiter
        lb = TokenBucketLimiter()
        result = await lb.check("user_123", "/api/items", limit=50, window_seconds=30)
    assert result.limit == 50
    assert result.window_seconds == 30
    assert result.remaining == 42
