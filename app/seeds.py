"""
Seeds demo API clients on first startup so you can test immediately.
"""

from sqlalchemy import select
from app.models import APIClient, AsyncSessionLocal


DEMO_CLIENTS = [
    {"api_key": "ak_free_demo_key_001",       "name": "Free Tier Demo",       "tier": "free",       "rate_limit": 10,   "window_seconds": 60},
    {"api_key": "ak_pro_demo_key_002",         "name": "Pro Tier Demo",         "tier": "pro",        "rate_limit": 300,  "window_seconds": 60},
    {"api_key": "ak_enterprise_demo_key_003",  "name": "Enterprise Tier Demo",  "tier": "enterprise", "rate_limit": 1000, "window_seconds": 60},
]


async def seed_clients():
    async with AsyncSessionLocal() as session:
        for client_data in DEMO_CLIENTS:
            exists = await session.scalar(
                select(APIClient).where(APIClient.api_key == client_data["api_key"])
            )
            if not exists:
                session.add(APIClient(**client_data))
        await session.commit()
