"""
Routes
------
Simulated product/user/item APIs to demo caching + rate limiting.
Admin routes for managing clients and inspecting system state.
"""

import hashlib
import secrets
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import APIClient, RequestLog, RateLimitEvent, get_db
from app.limiter import limiter
from app.cache import cache
from app.metrics import metrics

# ── Routers ──────────────────────────────────────────────────────────────────
api_router = APIRouter(prefix="/api", tags=["API"])
admin_router = APIRouter(prefix="/admin", tags=["Admin"])
system_router = APIRouter(tags=["System"])


# ── Schemas ───────────────────────────────────────────────────────────────────
class ClientCreate(BaseModel):
    name: str
    tier: str = "free"           # free | pro | enterprise
    rate_limit: Optional[int] = None
    window_seconds: Optional[int] = None


class ClientResponse(BaseModel):
    id: int
    api_key: str
    name: str
    tier: str
    rate_limit: int
    window_seconds: int
    is_active: bool
    created_at: datetime

    class Config:
        from_attributes = True


# Tier defaults
TIER_LIMITS = {
    "free":       {"rate_limit": 60,   "window_seconds": 60},
    "pro":        {"rate_limit": 300,  "window_seconds": 60},
    "enterprise": {"rate_limit": 1000, "window_seconds": 60},
}


# ── System routes ─────────────────────────────────────────────────────────────
@system_router.get("/health", tags=["System"])
async def health():
    return {"status": "ok", "timestamp": datetime.utcnow().isoformat()}


@system_router.get("/metrics", tags=["System"])
async def get_metrics():
    snapshot = await metrics.get_snapshot()
    cw = await metrics.cloudwatch_format()
    return {"metrics": snapshot, "cloudwatch_format": cw}


# ── Admin routes ──────────────────────────────────────────────────────────────
@admin_router.post("/clients", response_model=ClientResponse)
async def create_client(data: ClientCreate, db: AsyncSession = Depends(get_db)):
    """Register a new API client and get an API key."""
    tier_defaults = TIER_LIMITS.get(data.tier, TIER_LIMITS["free"])
    api_key = "ak_" + secrets.token_hex(24)
    client = APIClient(
        api_key=api_key,
        name=data.name,
        tier=data.tier,
        rate_limit=data.rate_limit or tier_defaults["rate_limit"],
        window_seconds=data.window_seconds or tier_defaults["window_seconds"],
    )
    db.add(client)
    await db.commit()
    await db.refresh(client)
    return client


@admin_router.get("/clients", response_model=list[ClientResponse])
async def list_clients(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(APIClient))
    return result.scalars().all()


@admin_router.delete("/clients/{api_key}/bucket")
async def reset_client_bucket(api_key: str, endpoint: str = Query(...)):
    """Manually reset a client's rate limit bucket."""
    reset = await limiter.reset_bucket(api_key, endpoint)
    return {"reset": reset, "api_key": api_key, "endpoint": endpoint}


@admin_router.get("/clients/{api_key}/bucket")
async def inspect_bucket(api_key: str, endpoint: str = Query(...)):
    """Inspect current token bucket state for a client."""
    state = await limiter.get_bucket_state(api_key, endpoint)
    return state


@admin_router.post("/cache/invalidate")
async def invalidate_cache(pattern: str = Query(...)):
    """Invalidate all cached responses matching a URL pattern."""
    count = await cache.invalidate(pattern)
    return {"invalidated_keys": count, "pattern": pattern}


@admin_router.get("/logs")
async def get_logs(
    limit: int = Query(50, le=500),
    api_key: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    query = select(RequestLog).order_by(RequestLog.timestamp.desc()).limit(limit)
    if api_key:
        query = query.where(RequestLog.api_key == api_key)
    result = await db.execute(query)
    logs = result.scalars().all()
    return [
        {
            "id": l.id,
            "api_key": l.api_key,
            "endpoint": l.endpoint,
            "method": l.method,
            "status_code": l.status_code,
            "latency_ms": l.latency_ms,
            "cache_hit": l.cache_hit,
            "rate_limited": l.rate_limited,
            "timestamp": l.timestamp.isoformat(),
        }
        for l in logs
    ]


@admin_router.get("/rate-limit-events")
async def get_rate_limit_events(
    limit: int = Query(50, le=500),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(RateLimitEvent)
        .order_by(RateLimitEvent.timestamp.desc())
        .limit(limit)
    )
    events = result.scalars().all()
    return [
        {
            "id": e.id,
            "api_key": e.api_key,
            "endpoint": e.endpoint,
            "limit": e.limit,
            "timestamp": e.timestamp.isoformat(),
        }
        for e in events
    ]


@admin_router.get("/stats/summary")
async def stats_summary(db: AsyncSession = Depends(get_db)):
    total_requests = await db.scalar(select(func.count(RequestLog.id)))
    total_throttled = await db.scalar(
        select(func.count(RequestLog.id)).where(RequestLog.rate_limited == True)
    )
    total_cache_hits = await db.scalar(
        select(func.count(RequestLog.id)).where(RequestLog.cache_hit == True)
    )
    avg_latency = await db.scalar(select(func.avg(RequestLog.latency_ms)))
    return {
        "total_requests": total_requests,
        "total_throttled": total_throttled,
        "total_cache_hits": total_cache_hits,
        "avg_latency_ms": round(avg_latency or 0, 2),
        "throttle_rate": round((total_throttled or 0) / max(total_requests, 1), 4),
        "cache_hit_rate": round((total_cache_hits or 0) / max(total_requests, 1), 4),
    }


# ── Simulated API endpoints (to demo rate limiting + caching) ─────────────────
@api_router.get("/products")
async def get_products(
    category: Optional[str] = None,
    page: int = Query(1, ge=1),
    limit: int = Query(10, le=100),
):
    """Simulated products list — responses are cached."""
    products = [
        {"id": i, "name": f"Product {i}", "category": category or "general", "price": round(i * 9.99, 2)}
        for i in range((page - 1) * limit + 1, page * limit + 1)
    ]
    return {"products": products, "page": page, "total": 1000}


@api_router.get("/products/{product_id}")
async def get_product(product_id: int):
    return {"id": product_id, "name": f"Product {product_id}", "price": product_id * 9.99}


@api_router.post("/products")
async def create_product(product: dict):
    """Mutates data — middleware will invalidate /api/products cache."""
    return {"id": 9999, **product, "created": True}


@api_router.get("/users/{user_id}")
async def get_user(user_id: int):
    return {"id": user_id, "name": f"User {user_id}", "email": f"user{user_id}@example.com"}


@api_router.get("/items")
async def get_items(q: Optional[str] = None):
    items = [{"id": i, "label": f"Item {i}", "query": q} for i in range(1, 11)]
    return {"items": items}


@api_router.get("/stats")
async def get_stats():
    """Fast-expiring cached endpoint (10s TTL)."""
    return {
        "active_users": 1423,
        "requests_today": 84201,
        "uptime_seconds": 3600 * 24 * 7,
    }
