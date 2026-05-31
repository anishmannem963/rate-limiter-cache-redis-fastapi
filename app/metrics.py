"""
Metrics
-------
Tracks live system health stats in Redis with a rolling time window.
Exposes a /metrics endpoint for dashboards and CloudWatch ingestion.
"""

import time
import json
from app.redis_client import get_redis
from app.config import get_settings

settings = get_settings()

METRICS_KEY = "metrics:requests"
LATENCY_KEY = "metrics:latencies"
THROTTLED_KEY = "metrics:throttled"


class MetricsCollector:

    async def record_request(
        self,
        endpoint: str,
        latency_ms: float,
        status_code: int,
        cache_hit: bool,
        rate_limited: bool,
        api_key: str = "anonymous",
    ) -> None:
        redis = await get_redis()
        now = time.time()
        window = settings.METRICS_WINDOW

        pipe = redis.pipeline()

        # Sliding window request count (sorted set with timestamp as score)
        pipe.zadd(METRICS_KEY, {f"{now}:{api_key}:{endpoint}": now})
        pipe.zremrangebyscore(METRICS_KEY, 0, now - window)

        # Latency list (keep last 1000)
        pipe.lpush(LATENCY_KEY, latency_ms)
        pipe.ltrim(LATENCY_KEY, 0, 999)

        # Throttled counter
        if rate_limited:
            pipe.incr(THROTTLED_KEY)

        # Per-endpoint counters
        pipe.incr(f"metrics:endpoint:{endpoint}:total")
        if cache_hit:
            pipe.incr(f"metrics:endpoint:{endpoint}:cache_hits")
        if status_code >= 500:
            pipe.incr(f"metrics:endpoint:{endpoint}:errors")

        await pipe.execute()

    async def get_snapshot(self) -> dict:
        redis = await get_redis()
        now = time.time()
        window = settings.METRICS_WINDOW

        # Requests in the last window
        req_count = await redis.zcount(METRICS_KEY, now - window, now)

        # Latency stats
        latencies_raw = await redis.lrange(LATENCY_KEY, 0, -1)
        latencies = [float(x) for x in latencies_raw]
        if latencies:
            latencies_sorted = sorted(latencies)
            n = len(latencies_sorted)
            avg_latency = sum(latencies_sorted) / n
            p50 = latencies_sorted[int(n * 0.50)]
            p95 = latencies_sorted[int(n * 0.95)]
            p99 = latencies_sorted[int(n * 0.99)]
        else:
            avg_latency = p50 = p95 = p99 = 0.0

        # Throttled total
        throttled = int(await redis.get(THROTTLED_KEY) or 0)

        # Cache stats
        hits = int(await redis.get("metrics:cache_hits") or 0)
        misses = int(await redis.get("metrics:cache_misses") or 0)
        total_cache = hits + misses
        hit_ratio = round(hits / total_cache, 4) if total_cache else 0.0

        # Active rate limit buckets
        buckets = await redis.keys("rl:bucket:*")

        # Cached keys
        cached_keys = await redis.keys("cache:*")

        return {
            "window_seconds": window,
            "requests_in_window": req_count,
            "requests_per_second": round(req_count / window, 2),
            "latency_ms": {
                "avg": round(avg_latency, 2),
                "p50": round(p50, 2),
                "p95": round(p95, 2),
                "p99": round(p99, 2),
            },
            "cache": {
                "hits": hits,
                "misses": misses,
                "hit_ratio": hit_ratio,
                "cached_keys": len(cached_keys),
            },
            "rate_limiting": {
                "total_throttled_requests": throttled,
                "active_buckets": len(buckets),
            },
        }

    async def cloudwatch_format(self) -> list[dict]:
        """
        Returns metrics in CloudWatch PutMetricData format.
        Use this with boto3 to push to AWS CloudWatch.
        """
        snapshot = await self.get_snapshot()
        timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        return [
            {"MetricName": "RequestsPerSecond",    "Value": snapshot["requests_per_second"],          "Unit": "Count/Second", "Timestamp": timestamp},
            {"MetricName": "P99LatencyMs",          "Value": snapshot["latency_ms"]["p99"],             "Unit": "Milliseconds", "Timestamp": timestamp},
            {"MetricName": "CacheHitRatio",         "Value": snapshot["cache"]["hit_ratio"],            "Unit": "None",         "Timestamp": timestamp},
            {"MetricName": "ThrottledRequests",     "Value": snapshot["rate_limiting"]["total_throttled_requests"], "Unit": "Count", "Timestamp": timestamp},
        ]


# Singleton
metrics = MetricsCollector()
