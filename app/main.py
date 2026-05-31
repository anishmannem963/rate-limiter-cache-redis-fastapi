"""
Scalable API Rate Limiting & Caching System
-------------------------------------------
Entry point. Wires together:
  - FastAPI app
  - Middleware (rate limiting + caching + metrics)
  - Routes (API, admin, system)
  - DB and Redis lifecycle
"""

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.models import init_db
from app.redis_client import get_redis, close_redis
from app.middleware import RateLimitCacheMiddleware
from app.routes import api_router, admin_router, system_router
from app.logger import get_logger
from app.seeds import seed_clients

settings = get_settings()
logger = get_logger("main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("Starting up — initialising DB and Redis...")
    await init_db()
    await get_redis()
    await seed_clients()
    logger.info("Ready.")
    yield
    # Shutdown
    logger.info("Shutting down...")
    await close_redis()


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="""
## Scalable API Rate Limiting & Caching System

A production-style backend demonstrating:

- **Token Bucket Rate Limiting** — per-client, per-endpoint, with burst support
- **Redis Response Cache** — TTL-based with cache invalidation on mutations
- **Request Deduplication** — stampede protection via Redis locks
- **Structured Observability** — JSON logs + live /metrics endpoint
- **CloudWatch-ready** — metrics exportable to AWS CloudWatch

### Quick start
1. Register a client: `POST /admin/clients`
2. Use the returned `api_key` in `X-API-Key` header
3. Hit `/api/products` repeatedly to see rate limiting and caching in action
4. Check `/metrics` to see live stats
    """,
    lifespan=lifespan,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Core middleware — order matters: this wraps all routes
app.add_middleware(RateLimitCacheMiddleware)

# Routers
app.include_router(system_router)
app.include_router(api_router)
app.include_router(admin_router)


@app.get("/", tags=["System"])
async def root():
    return {
        "service": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "docs": "/docs",
        "metrics": "/metrics",
        "health": "/health",
    }
