# app/main.py

import logging
import os
from contextlib import asynccontextmanager

import redis.asyncio as aioredis
from fastapi import FastAPI, Request
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from app.config.logging_config import configure_logging
from app.routers import chat, health
from app.services.audit_service import ensure_audit_table
from app.services.limiter import limiter
from app.services.semantic_cache import ensure_index
from app.services.metrics import start_metrics_server, record_rate_limit_hit

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    # --- Startup ---
    try:
        redis_url = os.getenv("REDIS_URL", "redis://redis:6379/0")
        redis_client = aioredis.from_url(redis_url)
        await ensure_index(redis_client)
        await redis_client.aclose()
        logger.info("Redis vector index ready")
    except Exception as e:
        logger.warning("Could not initialise Redis vector index: %s", str(e))

    try:
        await ensure_audit_table()
        # Start Prometheus metrics server on port 9090
        start_metrics_server(port=9090)
        logger.info("Metrics server started on port 9090")
    except Exception as e:
        logger.warning("Could not initialise audit table: %s", str(e))

    yield
    # --- Shutdown ---


app = FastAPI(title="nexus-ai-gateway", lifespan=lifespan)

app.state.limiter = limiter
async def _rate_limit_handler(request: Request, exc: RateLimitExceeded):
    record_rate_limit_hit()
    return _rate_limit_exceeded_handler(request, exc)

app.add_exception_handler(
    RateLimitExceeded,
    _rate_limit_handler,  # type: ignore[arg-type]
)
app.add_middleware(SlowAPIMiddleware)

app.include_router(chat.router)
app.include_router(health.router)


@app.get("/")
def read_root() -> dict:
    return {"message": "nexus-ai-gateway is running"}