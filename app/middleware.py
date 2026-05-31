"""
Middleware
----------
Intercepts every request:
  1. Identifies client (API key or IP fallback)
  2. Checks rate limit before hitting any route
  3. Returns cached response if available (GET only)
  4. After response: records metrics, logs, and caches result
"""

import time
import json
from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from app.limiter import limiter
from app.cache import cache
from app.metrics import metrics
from app.logger import get_logger, log_request
from app.models import RequestLog, RateLimitEvent, AsyncSessionLocal

logger = get_logger("middleware")

# Endpoints that bypass rate limiting (health checks, metrics)
EXEMPT_PATHS = {"/health", "/metrics", "/docs", "/openapi.json", "/redoc"}

# Only cache GET responses
CACHEABLE_METHODS = {"GET"}


class RateLimitCacheMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp):
        super().__init__(app)

    async def dispatch(self, request: Request, call_next) -> Response:
        start_time = time.time()
        path = request.url.path
        method = request.method

        # --- Identify client ---
        api_key = request.headers.get("X-API-Key") or request.client.host
        client_ip = request.client.host if request.client else "unknown"

        # --- Skip exempt paths ---
        if path in EXEMPT_PATHS:
            response = await call_next(request)
            return response

        # --- Rate limit check ---
        rate_limited = False
        rl_result = await limiter.check(
            identifier=api_key,
            endpoint=path,
        )

        if not rl_result.allowed:
            rate_limited = True
            latency_ms = (time.time() - start_time) * 1000

            # Async log to DB
            await self._log_to_db(
                api_key=api_key,
                client_ip=client_ip,
                endpoint=path,
                method=method,
                status_code=429,
                latency_ms=latency_ms,
                cache_hit=False,
                rate_limited=True,
                is_rate_event=True,
                rate_limit=rl_result.limit,
                window_seconds=rl_result.window_seconds,
            )

            await metrics.record_request(
                endpoint=path,
                latency_ms=latency_ms,
                status_code=429,
                cache_hit=False,
                rate_limited=True,
                api_key=api_key,
            )

            log_request(logger, api_key, path, method, 429, latency_ms,
                        False, True, client_ip)

            return JSONResponse(
                status_code=429,
                content={
                    "error": "Too Many Requests",
                    "detail": f"Rate limit of {rl_result.limit} req/{rl_result.window_seconds}s exceeded.",
                    "retry_after": rl_result.retry_after,
                },
                headers={
                    "Retry-After": str(rl_result.retry_after),
                    "X-RateLimit-Limit": str(rl_result.limit),
                    "X-RateLimit-Remaining": "0",
                    "X-RateLimit-Reset": str(rl_result.retry_after),
                },
            )

        # --- Cache check (GET only) ---
        cache_hit = False
        if method in CACHEABLE_METHODS:
            query_params = str(request.query_params)
            cached_data, cache_hit = await cache.get(path, query_params)
            if cache_hit:
                latency_ms = (time.time() - start_time) * 1000
                await metrics.record_request(
                    endpoint=path,
                    latency_ms=latency_ms,
                    status_code=200,
                    cache_hit=True,
                    rate_limited=False,
                    api_key=api_key,
                )
                log_request(logger, api_key, path, method, 200, latency_ms,
                            True, False, client_ip)
                return JSONResponse(
                    content=cached_data,
                    headers={
                        "X-Cache": "HIT",
                        "X-RateLimit-Remaining": str(rl_result.remaining),
                        "X-RateLimit-Limit": str(rl_result.limit),
                    },
                )

        # --- Process request ---
        response = await call_next(request)
        latency_ms = (time.time() - start_time) * 1000

        # --- Cache the response (GET + 2xx only) ---
        if method in CACHEABLE_METHODS and 200 <= response.status_code < 300:
            body_bytes = b""
            async for chunk in response.body_iterator:
                body_bytes += chunk
            try:
                body_data = json.loads(body_bytes)
                query_params = str(request.query_params)
                await cache.set(path, query_params, body_data)
            except Exception:
                pass
            response = Response(
                content=body_bytes,
                status_code=response.status_code,
                headers=dict(response.headers),
                media_type=response.media_type,
            )

        # Attach rate limit headers to every response
        response.headers["X-RateLimit-Limit"] = str(rl_result.limit)
        response.headers["X-RateLimit-Remaining"] = str(rl_result.remaining)
        response.headers["X-Cache"] = "MISS"

        # --- Record metrics and log ---
        await metrics.record_request(
            endpoint=path,
            latency_ms=latency_ms,
            status_code=response.status_code,
            cache_hit=False,
            rate_limited=False,
            api_key=api_key,
        )
        log_request(logger, api_key, path, method, response.status_code,
                    latency_ms, False, False, client_ip)

        await self._log_to_db(
            api_key=api_key,
            client_ip=client_ip,
            endpoint=path,
            method=method,
            status_code=response.status_code,
            latency_ms=latency_ms,
            cache_hit=cache_hit,
            rate_limited=False,
        )

        return response

    async def _log_to_db(
        self,
        api_key: str,
        client_ip: str,
        endpoint: str,
        method: str,
        status_code: int,
        latency_ms: float,
        cache_hit: bool,
        rate_limited: bool,
        is_rate_event: bool = False,
        rate_limit: int = 0,
        window_seconds: int = 0,
    ) -> None:
        try:
            async with AsyncSessionLocal() as session:
                log_entry = RequestLog(
                    api_key=api_key,
                    client_ip=client_ip,
                    endpoint=endpoint,
                    method=method,
                    status_code=status_code,
                    latency_ms=latency_ms,
                    cache_hit=cache_hit,
                    rate_limited=rate_limited,
                )
                session.add(log_entry)

                if is_rate_event:
                    event = RateLimitEvent(
                        api_key=api_key,
                        client_ip=client_ip,
                        endpoint=endpoint,
                        limit=rate_limit,
                        window_seconds=window_seconds,
                    )
                    session.add(event)

                await session.commit()
        except Exception as e:
            logger.warning(f"DB log failed: {e}")
