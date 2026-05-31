"""
Integration tests for the FastAPI routes.
Uses TestClient — no real Redis/DB needed.
"""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from fastapi.testclient import TestClient


def make_allow_result():
    from app.limiter import RateLimitResult
    return RateLimitResult(allowed=True, remaining=99, retry_after=0, limit=100, window_seconds=60)


def make_deny_result():
    from app.limiter import RateLimitResult
    return RateLimitResult(allowed=False, remaining=0, retry_after=10, limit=100, window_seconds=60)


@pytest.fixture
def client():
    with (
        patch("app.limiter.get_redis", new_callable=lambda: lambda: AsyncMock()),
        patch("app.cache.get_redis",   new_callable=lambda: lambda: AsyncMock()),
        patch("app.metrics.get_redis", new_callable=lambda: lambda: AsyncMock()),
        patch("app.models.engine"),
        patch("app.models.init_db",    new_callable=lambda: lambda: AsyncMock()),
        patch("app.seeds.seed_clients",new_callable=lambda: lambda: AsyncMock()),
    ):
        from app.main import app
        return TestClient(app, raise_server_exceptions=False)


def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_root(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert "docs" in resp.json()


def test_get_products_returns_list(client):
    resp = client.get("/api/products", headers={"X-API-Key": "ak_pro_demo_key_002"})
    assert resp.status_code == 200
    body = resp.json()
    assert "products" in body
    assert len(body["products"]) == 10


def test_rate_limit_headers_present(client):
    resp = client.get("/api/products", headers={"X-API-Key": "test_key"})
    assert "x-ratelimit-limit" in resp.headers
    assert "x-ratelimit-remaining" in resp.headers


def test_get_single_product(client):
    resp = client.get("/api/products/42", headers={"X-API-Key": "test_key"})
    assert resp.status_code == 200
    assert resp.json()["id"] == 42


def test_get_user(client):
    resp = client.get("/api/users/7", headers={"X-API-Key": "test_key"})
    assert resp.status_code == 200
    assert resp.json()["id"] == 7


def test_metrics_endpoint(client):
    resp = client.get("/metrics")
    assert resp.status_code == 200
    body = resp.json()
    assert "metrics" in body
    assert "cloudwatch_format" in body
