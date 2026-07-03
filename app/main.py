# app/main.py

import logging
import os
from contextlib import asynccontextmanager

import redis.asyncio as aioredis
from fastapi import FastAPI

from app.routers import chat, health
from app.services.semantic_cache import ensure_index

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Manages application startup and shutdown lifecycle.
    Startup: creates Redis vector index if it doesn't exist.
    Shutdown: nothing to clean up currently — documented as a
    known gap if connection pooling is added in production hardening.
    """
    # --- Startup ---
    try:
        redis_url = os.getenv("REDIS_URL", "redis://redis:6379/0")
        redis_client = aioredis.from_url(redis_url)
        await ensure_index(redis_client)
        await redis_client.aclose()
        logger.info("Redis vector index ready")
    except Exception as e:
        logger.warning("Could not initialise Redis vector index: %s", str(e))

    yield  # application runs here

    # --- Shutdown ---
    # Nothing to teardown at this stage.


app = FastAPI(title="nexus-ai-gateway", lifespan=lifespan)

app.include_router(chat.router)
app.include_router(health.router)


@app.get("/")
def read_root() -> dict:
    return {"message": "nexus-ai-gateway is running"}