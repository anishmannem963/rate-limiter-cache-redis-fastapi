# demo.html — Explanation & Interview Guide

> A complete walkthrough of the interactive demo for the **Scalable API Rate Limiting & Caching System**.  
> Use this as your reference when walking an interviewer through the project.

---

## What the demo is

`demo.html` is a fully self-contained browser demo that **simulates the entire backend** — no server needed, no internet needed. Every concept in the real project (token bucket, Redis cache, cache invalidation, TTL decay, request metrics) is faithfully reproduced in JavaScript so you can demo it live during any interview, on any machine, instantly.

Open it like this:

```bash
# From the project root
open demo.html          # macOS
start demo.html         # Windows
xdg-open demo.html      # Linux
```

---

## Layout — 3 panels

```
┌─────────────────┬───────────────────────────┬──────────────────┐
│   LEFT PANEL    │      CENTER PANEL         │   RIGHT PANEL    │
│                 │                           │                  │
│  • API Client   │  • Stats bar              │  • Lifecycle     │
│  • Endpoint     │  • Request feed           │    animation     │
│  • Fire controls│  • Token bucket bar       │  • Last response │
│  • Scenarios    │                           │  • Metrics cards │
│                 │                           │  • Cache state   │
└─────────────────┴───────────────────────────┴──────────────────┘
```

---

## Panel-by-panel explanation

### Left panel — Controls

**API Client selector**

Click any client card to switch the active identity. Each client has a different rate limit tier, simulating real-world multi-tenant API management.

| Client | API Key | Rate Limit | Burst Capacity | Window |
|--------|---------|------------|----------------|--------|
| Free Tier | `ak_free_demo_key_001` | 10 req | 15 req | 60s |
| Pro Tier | `ak_pro_demo_key_002` | 300 req | 450 req | 60s |
| Enterprise | `ak_enterprise_demo_key_003` | 1000 req | 1500 req | 60s |

Burst capacity is `limit × 1.5`. This is the token bucket's **max capacity** — the system tolerates short bursts above the base rate but the bucket drains faster than it refills when sustained.

**Endpoint selector**

Choose which API endpoint to hit. Each has different caching behavior:

| Method | Endpoint | Cached? | TTL | Notes |
|--------|----------|---------|-----|-------|
| GET | `/api/products` | Yes | 60s | Product list |
| GET | `/api/products/42` | Yes | 60s | Single product |
| GET | `/api/users/7` | Yes | 30s | User lookup |
| GET | `/api/stats` | Yes | 10s | Fast-expiring stats |
| POST | `/api/products` | No | — | Triggers cache invalidation |
| GET | `/metrics` | No | — | Exempt from rate limiting |

**Fire controls**

- **Count slider (1–20):** how many requests to fire in one click
- **Delay slider (0–500ms):** pause between each request in the batch
- **Send Request button:** fires the configured count with the configured delay
- **Burst Attack button:** fires `maxTokens + 5` requests with 30ms delay — guaranteed to exhaust the bucket and produce 429s

---

### Center panel — Live feed

**Stats bar** (updates after every request)

| Stat | What it counts |
|------|---------------|
| Total | All requests fired this session |
| 200 OK | Successful responses |
| 429 Throttled | Rate-limited responses |
| Cache Hits | Responses served from Redis cache |
| Avg Latency | Rolling average across all requests |

**Request feed**

Each row shows one request. Color-coded by outcome:

| Row color | Meaning | Left border |
|-----------|---------|-------------|
| Dark green | Normal 200 response | Green |
| Dark blue | Cache hit — served from Redis | Blue |
| Dark red | Rate limited — 429 returned | Red |

Columns per row: `timestamp · status · method · path · [tag] · latency`

Tags that appear:
- `CACHE HIT` (blue) — response came from Redis, backend never called
- `THROTTLED` (red) — token bucket was empty, 429 returned

**Token bucket bar** (bottom of center panel)

Shows the current token count for the active client. Color changes by fill level:

| Bar color | Tokens remaining | Meaning |
|-----------|-----------------|---------|
| Green | > 60% | Healthy, plenty of capacity |
| Amber | 25–60% | Getting low, high traffic |
| Red | < 25% | Nearly exhausted, 429s imminent |

Tokens refill in real time at `limit / window` per second (same as the real Lua script).

---

### Right panel — Detail

**Request lifecycle animation**

Every request animates through the 5 middleware steps. The animation short-circuits at the step where the request ends — so you can visually see *exactly* which step stopped it.

| Step | Name | Color when passed | Color when stopped |
|------|------|------------------|--------------------|
| 1 | Identify client | Blue (active) | — |
| 2 | Token bucket check | Green | Red (429 here) |
| 3 | Cache lookup | Green | Red (cache HIT ends here) |
| 4 | Route handler | Green | — |
| 5 | Cache + log | Green | — |

When a request is rate-limited, steps 3–5 are never reached. When a cache hit occurs, steps 4–5 are never reached. This directly mirrors what the real middleware does.

**Last response panel**

Shows the JSON response body with syntax highlighting, plus the response headers that matter:

| Header | When present | Example |
|--------|-------------|---------|
| `X-RateLimit-Remaining` | All non-429 responses | `X-RateLimit-Remaining: 8` |
| `X-Cache` | All GET responses | `X-Cache: HIT` or `X-Cache: MISS` |
| `Retry-After` | 429 responses only | `Retry-After: 60` |

**Metrics cards**

| Metric | Formula | What it tells you |
|--------|---------|------------------|
| Requests/sec | `requestsInLast60s / 60` | Current traffic rate |
| Cache hit ratio | `cacheHits / totalRequests` | Cache effectiveness |
| p99 latency | 99th percentile of all latencies | Worst-case response time |
| Throttle rate | `throttled / total` | How aggressively the limiter fires |

**Redis cache state**

Lists every active cache entry with a live TTL countdown bar. The bar drains in real time. When it hits zero, the entry disappears — exactly like `EXPIRE` in Redis.

---

## Scenarios — step by step

### Scenario 1: Cache Hit / Miss
**Button:** "Demo: Cache Hit / Miss"

What happens:
1. `GET /api/products` fires — cache is empty, response is a **MISS**, backend called, entry stored with 60s TTL
2. Same request fires again — cache has the entry, response is a **HIT**, 2–12ms latency (vs 20–80ms for a miss)
3. Third request — still a **HIT**

**What to say in an interview:**
> "The first request populates the cache. Every subsequent request for the same endpoint returns in under 12ms from Redis instead of going to the database. You can see the cache entry appear in the bottom-right panel with a live TTL countdown. This is how we achieve sub-50ms latency for repeated reads."

Expected feed output:
```
12:04:01.203   200   GET   /api/products              47ms   ← MISS, slow
12:04:01.503   200   GET   /api/products   CACHE HIT   5ms   ← HIT, fast
12:04:01.803   200   GET   /api/products   CACHE HIT   3ms   ← HIT, fast
```

---

### Scenario 2: Trigger 429s
**Button:** "Demo: Trigger 429s"

What happens:
1. Switches to **Free Tier** client (limit: 10/60s, burst: 15)
2. Fires 18 requests in quick succession
3. First 15 succeed (burst capacity = 15), requests 16–18 return 429

**What to say in an interview:**
> "This client's bucket holds 15 tokens at max capacity — the base limit of 10 multiplied by the burst multiplier of 1.5. Once the bucket drains, every request gets a 429 with a Retry-After header telling the client how long to wait. Notice the token bucket bar turns red and the lifecycle animation stops at step 2 — the route handler is never reached."

Expected feed output:
```
...
12:04:02.100   200   GET   /api/products              34ms   ← token 1
...
12:04:02.550   200   GET   /api/products              28ms   ← token 15 (last)
12:04:02.580   429   GET   /api/products   THROTTLED   2ms   ← bucket empty
12:04:02.610   429   GET   /api/products   THROTTLED   1ms
12:04:02.640   429   GET   /api/products   THROTTLED   2ms
```

Token bucket after burst:
```
Tokens: 0 / 15   [████████████████████ RED BAR]
```

---

### Scenario 3: Cache Invalidation
**Button:** "Demo: Cache Invalidation"

What happens:
1. `GET /api/products` — MISS, response cached
2. `GET /api/products` — HIT, served from cache
3. `POST /api/products` — mutation fires, **clears the cache entry** for `/api/products`
4. `GET /api/products` — MISS again, cache was wiped, backend called

**What to say in an interview:**
> "This is the classic cache invalidation problem. When a mutation happens — a POST, PUT, or DELETE — the middleware pattern-matches and evicts all cache keys for that resource. The next GET is a cold miss again. You can watch the cache entry disappear from the bottom-right panel the moment the POST fires."

Expected feed output:
```
12:04:05.100   200   GET    /api/products              52ms   ← MISS
12:04:05.500   200   GET    /api/products   CACHE HIT   4ms   ← HIT
12:04:05.900   200   POST   /api/products              31ms   ← invalidates cache
12:04:06.200   200   GET    /api/products              48ms   ← MISS again
```

---

## Manual test cases

These are tests you can run yourself to verify each behavior.

### Test 1 — Basic rate limiting

| Step | Action | Expected result |
|------|--------|----------------|
| 1 | Select Free Tier client | Bucket shows 15/15 tokens |
| 2 | Set count = 1, click Send | 200 response, tokens = 14 |
| 3 | Set count = 14, click Send | All 200, tokens = 0 |
| 4 | Click Send again | 429 THROTTLED, Retry-After header appears |
| 5 | Wait 6 seconds | Tokens partially refill (1 token/sec) |
| 6 | Click Send | 200 again — bucket refilled |

---

### Test 2 — Cache TTL expiry

| Step | Action | Expected result |
|------|--------|----------------|
| 1 | Select `/api/stats` endpoint (10s TTL) | — |
| 2 | Click Send | 200 MISS, cache entry appears with 10s bar |
| 3 | Click Send immediately | 200 CACHE HIT, bar at ~9s |
| 4 | Wait 10 seconds | Cache entry disappears from panel |
| 5 | Click Send | 200 MISS again — TTL expired |

---

### Test 3 — Metrics endpoint is exempt

| Step | Action | Expected result |
|------|--------|----------------|
| 1 | Select Free Tier, exhaust all tokens with Burst button | 429s firing |
| 2 | Switch endpoint to `/metrics` | — |
| 3 | Click Send | 200 response, no 429 — exempt path bypasses rate limiter |
| 4 | Check lifecycle animation | Only step 1 lights up — skips straight through |

---

### Test 4 — Enterprise vs Free tier

| Step | Action | Expected result |
|------|--------|----------------|
| 1 | Select Free Tier, click Burst Attack | 429s after ~15 requests |
| 2 | Select Enterprise Tier | Bucket resets to 1500/1500 |
| 3 | Set count = 20, delay = 0, click Send 5 times | All 200 — 1500 token capacity |
| 4 | Watch throttle rate metric | Stays at 0% for Enterprise |

---

### Test 5 — p99 latency difference (cache vs no cache)

| Step | Action | Expected result |
|------|--------|----------------|
| 1 | Select Pro Tier, `/api/products` | — |
| 2 | Fire 5 requests one at a time | Avg latency ~20–80ms (all misses at first) |
| 3 | Fire 10 more requests rapidly | Avg latency drops to ~2–12ms (cache hits) |
| 4 | Check p99 card | p99 is in the 2–12ms range after cache warms up |

---

## Key numbers reference

| Parameter | Free | Pro | Enterprise | Source in code |
|-----------|------|-----|------------|---------------|
| Base rate limit | 10 req/min | 300 req/min | 1000 req/min | `seeds.py` |
| Burst multiplier | 1.5× | 1.5× | 1.5× | `config.py` |
| Max bucket tokens | 15 | 450 | 1500 | `limiter.py` |
| Token refill rate | 0.167/s | 5/s | 16.7/s | `limiter.py` (limit/window) |
| `/api/products` TTL | 60s | 60s | 60s | `cache.py` |
| `/api/users` TTL | 30s | 30s | 30s | `cache.py` |
| `/api/stats` TTL | 10s | 10s | 10s | `cache.py` |
| Cache hit latency | 2–12ms | 2–12ms | 2–12ms | `simulateRequest()` |
| Cache miss latency | 20–80ms | 20–80ms | 20–80ms | `simulateRequest()` |
| Rate limit check latency | 1–5ms | 1–5ms | 1–5ms | `simulateRequest()` |
| Metrics window | 60s | 60s | 60s | `metrics.py` |

---

## What the demo does NOT simulate

The demo is faithful but it is a simulation, not a live backend. These things are mocked:

| Real system | Demo equivalent |
|-------------|----------------|
| Redis Lua script (atomic) | JavaScript token counter in memory |
| PostgreSQL audit log | Not persisted — resets on page reload |
| Docker + AWS ECS | Single HTML file, no infra needed |
| Concurrent users from different IPs | Single simulated client per session |
| Actual network latency | `randInt()` to produce realistic latency ranges |

---

## Suggested interview walkthrough (3 minutes)

1. **Open the file** — "This is the live demo, no server needed."
2. **Run Scenario 1 (Cache)** — "Watch the first request — MISS, ~50ms. Second request — HIT, ~5ms from Redis. You can see the TTL bar counting down."
3. **Run Scenario 2 (429s)** — "Now I switch to the Free Tier — 10 req/min. I fire a burst. The bucket drains, and you can see 429s with Retry-After headers. The lifecycle animation shows the request dying at step 2, before it ever reaches the route handler."
4. **Run Scenario 3 (Invalidation)** — "Now the cache invalidation story. GET caches it. POST wipes it. Next GET is a cold miss again."
5. **Point to metrics cards** — "These are the same metrics I push to CloudWatch in the real system — RPS, p99, cache hit ratio, throttle rate."
6. **Offer to show the code** — "The real implementation is in `app/limiter.py` — the Lua script runs atomically inside Redis so there are no race conditions under high concurrency."
