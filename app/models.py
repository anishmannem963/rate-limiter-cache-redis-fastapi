from datetime import datetime
from sqlalchemy import Column, Integer, String, Float, DateTime, Boolean, Text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from app.config import get_settings

settings = get_settings()

engine = create_async_engine(
    settings.postgres_url,
    echo=settings.DEBUG,
    pool_size=10,
    max_overflow=20,
)

AsyncSessionLocal = sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    pass


class APIClient(Base):
    """Registered API clients with their rate limit tiers."""
    __tablename__ = "api_clients"

    id = Column(Integer, primary_key=True, index=True)
    api_key = Column(String(64), unique=True, index=True, nullable=False)
    name = Column(String(128), nullable=False)
    tier = Column(String(32), default="free")        # free | pro | enterprise
    rate_limit = Column(Integer, default=100)         # requests per window
    window_seconds = Column(Integer, default=60)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class RequestLog(Base):
    """Persistent log of every API request for audit and analytics."""
    __tablename__ = "request_logs"

    id = Column(Integer, primary_key=True, index=True)
    api_key = Column(String(64), index=True)
    client_ip = Column(String(45))
    endpoint = Column(String(256))
    method = Column(String(10))
    status_code = Column(Integer)
    latency_ms = Column(Float)
    cache_hit = Column(Boolean, default=False)
    rate_limited = Column(Boolean, default=False)
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)
    user_agent = Column(Text, nullable=True)


class RateLimitEvent(Base):
    """Tracks every rate limit breach for monitoring and alerting."""
    __tablename__ = "rate_limit_events"

    id = Column(Integer, primary_key=True, index=True)
    api_key = Column(String(64), index=True)
    client_ip = Column(String(45))
    endpoint = Column(String(256))
    limit = Column(Integer)
    window_seconds = Column(Integer)
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)


async def get_db():
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
