"""
Load Test — Locust
------------------
Simulates realistic traffic patterns:
  - 80% GETs (to hit cache + rate limiter)
  - 15% user lookups
  - 5%  POSTs (to trigger cache invalidation)

Run:
  locust -f load_test/locustfile.py --host=http://localhost:8000

Or headless (CI):
  locust -f load_test/locustfile.py --host=http://localhost:8000 \
         --users 500 --spawn-rate 50 --run-time 60s --headless
"""

import random
from locust import HttpUser, task, between, events


# Demo API keys seeded at startup
API_KEYS = [
    "ak_free_demo_key_001",
    "ak_pro_demo_key_002",
    "ak_enterprise_demo_key_003",
]


class APIUser(HttpUser):
    """Simulates a normal API consumer."""
    wait_time = between(0.05, 0.3)    # 50–300ms between requests

    def on_start(self):
        self.api_key = random.choice(API_KEYS)
        self.headers = {"X-API-Key": self.api_key}

    @task(50)
    def get_products(self):
        page = random.randint(1, 10)
        self.client.get(f"/api/products?page={page}&limit=10", headers=self.headers, name="/api/products")

    @task(20)
    def get_single_product(self):
        pid = random.randint(1, 100)
        self.client.get(f"/api/products/{pid}", headers=self.headers, name="/api/products/{id}")

    @task(15)
    def get_user(self):
        uid = random.randint(1, 50)
        self.client.get(f"/api/users/{uid}", headers=self.headers, name="/api/users/{id}")

    @task(10)
    def get_items(self):
        self.client.get("/api/items", headers=self.headers)

    @task(3)
    def get_stats(self):
        self.client.get("/api/stats", headers=self.headers)

    @task(2)
    def create_product(self):
        """POST to trigger cache invalidation."""
        self.client.post(
            "/api/products",
            json={"name": f"New Product {random.randint(1,1000)}", "price": round(random.uniform(5, 200), 2)},
            headers=self.headers,
            name="/api/products [POST]",
        )


class HeavyUser(HttpUser):
    """Simulates an aggressive client that will get rate limited."""
    wait_time = between(0.01, 0.05)   # very fast — will hit rate limit
    weight = 1                         # fewer of these

    def on_start(self):
        # Free tier has the lowest limit — will get throttled quickly
        self.headers = {"X-API-Key": "ak_free_demo_key_001"}

    @task
    def hammer_products(self):
        self.client.get("/api/products", headers=self.headers, name="/api/products [HEAVY]")


class AdminUser(HttpUser):
    """Simulates ops checking metrics."""
    wait_time = between(2, 5)
    weight = 1

    @task(3)
    def check_metrics(self):
        self.client.get("/metrics")

    @task(2)
    def check_health(self):
        self.client.get("/health")

    @task(1)
    def check_logs(self):
        self.client.get("/admin/logs?limit=10")


@events.request.add_listener
def on_request(request_type, name, response_time, response_length, response, **kwargs):
    """Log rate limit hits to Locust stats."""
    if response and response.status_code == 429:
        print(f"[RATE LIMITED] {name} — retry after {response.headers.get('Retry-After', '?')}s")
