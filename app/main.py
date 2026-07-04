# app/main.py

import logging
import os
from contextlib import asynccontextmanager

import redis.asyncio as aioredis
from fastapi import FastAPI

from app.routers import chat, health
from app.services.audit_service import ensure_audit_table
from app.services.semantic_cache import ensure_index

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
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
    except Exception as e:
        logger.warning("Could not initialise audit table: %s", str(e))

    yield

    # --- Shutdown ---


app = FastAPI(title="nexus-ai-gateway", lifespan=lifespan)

app.include_router(chat.router)
app.include_router(health.router)


@app.get("/")
def read_root() -> dict:
    return {"message": "nexus-ai-gateway is running"}