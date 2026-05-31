"""
Tests for the Redis Response Cache.
"""


import pytest
import json
from unittest.mock import AsyncMock, patch


@pytest.fixture
def mock_redis():
    return AsyncMock()


@pytest.mark.asyncio
async def test_cache_miss(mock_redis):
    """Should return None and False on cache miss."""
    mock_redis.get = AsyncMock(return_value=None)
    mock_redis.incr = AsyncMock()
    with patch("app.cache.get_redis", return_value=mock_redis):
        from app.cache import ResponseCache
        c = ResponseCache()
        data, hit = await c.get("/api/products", "")
    assert data is None
    assert hit is False


@pytest.mark.asyncio
async def test_cache_hit(mock_redis):
    """Should return cached data and True on hit."""
    payload = {"products": [{"id": 1}]}
    mock_redis.get = AsyncMock(return_value=json.dumps(payload))
    mock_redis.incr = AsyncMock()
    with patch("app.cache.get_redis", return_value=mock_redis):
        from app.cache import ResponseCache
        c = ResponseCache()
        data, hit = await c.get("/api/products", "")
    assert hit is True
    assert data == payload


@pytest.mark.asyncio
async def test_cache_set(mock_redis):
    """Should call setex with correct TTL."""
    mock_redis.setex = AsyncMock()
    mock_redis.delete = AsyncMock()
    with patch("app.cache.get_redis", return_value=mock_redis):
        from app.cache import ResponseCache
        c = ResponseCache()
        await c.set("/api/products", "", {"ok": True}, ttl=60)
    mock_redis.setex.assert_called_once()
    args = mock_redis.setex.call_args[0]
    assert args[1] == 60                         # TTL
    assert json.loads(args[2]) == {"ok": True}   # payload


@pytest.mark.asyncio
async def test_cache_invalidate(mock_redis):
    """Should delete all keys matching the pattern."""
    mock_redis.keys = AsyncMock(return_value=["cache:abc:key1", "cache:def:key2"])
    mock_redis.delete = AsyncMock(return_value=2)
    with patch("app.cache.get_redis", return_value=mock_redis):
        from app.cache import ResponseCache
        c = ResponseCache()
        count = await c.invalidate("/api/products")
    assert count == 2


@pytest.mark.asyncio
async def test_cache_invalidate_no_keys(mock_redis):
    """Should return 0 if no keys match."""
    mock_redis.keys = AsyncMock(return_value=[])
    with patch("app.cache.get_redis", return_value=mock_redis):
        from app.cache import ResponseCache
        c = ResponseCache()
        count = await c.invalidate("/api/nonexistent")
    assert count == 0


@pytest.mark.asyncio
async def test_ttl_mapping():
    """Should use correct TTL per endpoint prefix."""
    from app.cache import _get_ttl
    assert _get_ttl("/api/products/123") == 60
    assert _get_ttl("/api/users/1") == 30
    assert _get_ttl("/api/stats") == 10
    assert _get_ttl("/api/items") == 45
    assert _get_ttl("/unknown/endpoint") == 30   # default


@pytest.mark.asyncio
async def test_cache_key_is_unique_per_params():
    """Same endpoint, different query params → different cache keys."""
    from app.cache import _cache_key
    k1 = _cache_key("/api/products", "page=1")
    k2 = _cache_key("/api/products", "page=2")
    k3 = _cache_key("/api/products", "")
    assert k1 != k2
    assert k1 != k3
