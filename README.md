# Scalable API Rate Limiting & Caching System

A production-style backend system built with **FastAPI**, **Redis**, and **PostgreSQL** — demonstrating token bucket rate limiting, response caching, request deduplication, and live observability.


---

## What it does

### Token Bucket Rate Limiting
- Per-client, per-endpoint rate limiting using the **token bucket algorithm**
- Atomic enforcement via a **Redis Lua script** — no race conditions under concurrency
- Configurable limits per client tier: Free (10/min), Pro (300/min), Enterprise (1000/min)
- Returns `429 Too Many Requests` with `Retry-After` header when exceeded
- Controlled burst support above the base limit

### Response Caching
- **Redis-backed** cache with per-endpoint TTL configuration
- Cache invalidation on mutations (POST/PUT/DELETE wipes related GET cache)
- **Stampede protection** — in-flight request deduplication via Redis locks
- Cache key includes query params for correctness

### Observability
- **Structured JSON logs** on every request — compatible with CloudWatch Logs Insights
- `/metrics` endpoint with live stats: RPS, p50/p95/p99 latency, cache hit ratio, throttle count
- CloudWatch `PutMetricData`-compatible export format
- All requests persisted to PostgreSQL for audit and analytics

---

## Architecture

```
Client Request
     │
     ▼
┌─────────────────────────────┐
│     RateLimitCacheMiddleware │  ← wraps every route
│                             │
│  1. Identify client         │  ← X-API-Key header or IP
│  2. Check token bucket      │  ← Redis Lua (atomic)
│     └─ 429 if empty         │
│  3. Check response cache    │  ← Redis GET (cache HIT → return immediately)
│  4. Forward to route        │  ← cache MISS → hit the handler
│  5. Cache the response      │  ← Redis SET with TTL
│  6. Record metrics + log    │  ← Redis + PostgreSQL
└─────────────────────────────┘
     │
     ▼
┌────────────┐   ┌───────────┐   ┌────────────┐
│  FastAPI   │   │   Redis   │   │ PostgreSQL │
│  Routes    │   │  (cache + │   │  (logs +   │
│            │   │  buckets) │   │   clients) │
└────────────┘   └───────────┘   └────────────┘
```

---

## Quick Start

**Requirements:** Docker + Docker Compose

```bash
git clone https://github.com/YOUR_USERNAME/rate-limiter.git
cd rate-limiter
cp .env.example .env
docker-compose up --build
```

The API is now live at `http://localhost:8000`

- **Swagger UI:** http://localhost:8000/docs
- **Metrics:** http://localhost:8000/metrics
- **Health:** http://localhost:8000/health

---

## Demo Walkthrough

Three demo API keys are seeded automatically:

| Key | Tier | Limit |
|-----|------|-------|
| `ak_free_demo_key_001` | Free | 10 req/min |
| `ak_pro_demo_key_002` | Pro | 300 req/min |
| `ak_enterprise_demo_key_003` | Enterprise | 1000 req/min |

### 1. Hit the API normally
```bash
curl http://localhost:8000/api/products \
  -H "X-API-Key: ak_pro_demo_key_002"
```

Response headers show rate limit state:
```
X-RateLimit-Limit: 300
X-RateLimit-Remaining: 299
X-Cache: MISS
```

### 2. Hit it again — cache kicks in
```bash
curl http://localhost:8000/api/products \
  -H "X-API-Key: ak_pro_demo_key_002"
```
```
X-Cache: HIT        ← served from Redis, no DB call
```

### 3. Trigger rate limiting (free tier = 10/min)
```bash
for i in {1..15}; do
  curl -s -o /dev/null -w "%{http_code}\n" \
    http://localhost:8000/api/products \
    -H "X-API-Key: ak_free_demo_key_001"
done
# First 10: 200, remaining: 429
```

### 4. Check live metrics
```bash
curl http://localhost:8000/metrics | python3 -m json.tool
```

### 5. Register a new client
```bash
curl -X POST http://localhost:8000/admin/clients \
  -H "Content-Type: application/json" \
  -d '{"name": "My App", "tier": "pro"}'
# Returns your new api_key
```

### 6. Run the load test
```bash
pip install locust
locust -f load_test/locustfile.py --host=http://localhost:8000
# Open http://localhost:8089 for the Locust dashboard
# Set users=500, spawn_rate=50 to see rate limiting under load
```

---

## Project Structure

```
rate-limiter/
├── app/
│   ├── main.py          # FastAPI app, lifespan, router wiring
│   ├── config.py        # Settings via pydantic-settings + .env
│   ├── middleware.py    # Core middleware: rate limit + cache + metrics
│   ├── limiter.py       # Token bucket algorithm (Redis Lua)
│   ├── cache.py         # Response cache + stampede protection
│   ├── metrics.py       # Live stats collector + CloudWatch exporter
│   ├── models.py        # SQLAlchemy async models + DB session
│   ├── routes.py        # All API + admin routes
│   ├── seeds.py         # Demo client seeding
│   └── logger.py        # Structured JSON logger
├── tests/
│   ├── test_limiter.py  # Token bucket unit tests
│   ├── test_cache.py    # Cache unit tests
│   └── test_routes.py   # Route integration tests
├── load_test/
│   └── locustfile.py    # Locust load test (3 user profiles)
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── pytest.ini
└── .env.example
```

---

## Running Tests

```bash
# Install deps locally
python -m venv venv
source venv/bin/activate    # Windows: venv\Scripts\activate
pip install -r requirements.txt

# Run tests
pytest

# With coverage
pytest --cov=app --cov-report=term-missing
```

---

## Key Design Decisions

### Why Token Bucket over Fixed Window?
Fixed window counters allow **2x burst at boundaries** — if your limit is 100/min, a client can send 100 at 11:59 and 100 at 12:00, hitting you with 200 in 2 seconds. Token bucket smooths this by refilling tokens continuously at a fixed rate.

### Why Lua scripts for rate limiting?
Redis is single-threaded, but multiple app servers can race on read-modify-write. A Lua script runs atomically inside Redis — the check and update happen in a single operation with no possibility of interleaving.

### Why fail open on Redis errors?
If Redis goes down, blocking all traffic causes an outage worse than the rate limiting issue. The system logs the Redis failure and allows requests through — trading safety for availability during infrastructure failures.

### Cache invalidation strategy
Rather than tracking exact cache keys per resource, the system uses **pattern-based invalidation** — a POST to `/api/products` deletes all cache keys matching `*api/products*`. Simple and correct at this scale; for larger systems you'd use a tag-based approach.

---

## API Reference

### System
| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Health check |
| GET | `/metrics` | Live metrics snapshot |

### API (requires X-API-Key header)
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/products` | List products (cached 60s) |
| GET | `/api/products/{id}` | Single product |
| POST | `/api/products` | Create product (invalidates cache) |
| GET | `/api/users/{id}` | Get user (cached 30s) |
| GET | `/api/items` | List items (cached 45s) |
| GET | `/api/stats` | System stats (cached 10s) |

### Admin
| Method | Path | Description |
|--------|------|-------------|
| POST | `/admin/clients` | Register new API client |
| GET | `/admin/clients` | List all clients |
| GET | `/admin/logs` | Request audit log |
| GET | `/admin/stats/summary` | Aggregate DB stats |
| DELETE | `/admin/clients/{key}/bucket` | Reset rate limit bucket |
| POST | `/admin/cache/invalidate` | Manually invalidate cache |

---

## Technologies

| | Tool | Why |
|---|---|---|
| API | FastAPI | Async, fast, auto-docs |
| Cache + Rate Limit | Redis 7 | Sub-millisecond, atomic Lua, TTL support |
| Database | PostgreSQL 15 | Audit logs, client registry |
| ORM | SQLAlchemy 2 async | Type-safe, async-native |
| Containers | Docker + Compose | One-command setup |
| Load Testing | Locust | Realistic multi-profile traffic simulation |
| Testing | pytest + pytest-asyncio | Async-compatible unit tests |

---

