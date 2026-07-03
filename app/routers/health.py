# app/routers/health.py

import os

import asyncpg
import redis.asyncio as aioredis
from fastapi import APIRouter, Response, status
from fastapi.responses import PlainTextResponse
from app.providers import anthropic_provider, ollama_provider, openai_provider

from app.config.settings import settings

router = APIRouter()

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")

_PROVIDER_CHECKS = {
    "openai": openai_provider.health_check,
    "anthropic": anthropic_provider.health_check,
    "ollama": ollama_provider.health_check,
}

_METRICS_STUB = """\
# HELP nexus_ai_gateway_up Whether the gateway process is serving requests.
# TYPE nexus_ai_gateway_up gauge
nexus_ai_gateway_up 1
"""


async def _check_redis() -> dict[str, str]:
    client = aioredis.from_url(REDIS_URL)
    try:
        await client.ping()
        return {"status": "ok"}
    except Exception:
        return {"status": "error"}
    finally:
        await client.aclose()


async def _check_database() -> dict[str, str]:
    if not settings.POSTGRES_URL:
        return {"status": "skipped"}

    try:
        conn = await asyncpg.connect(settings.POSTGRES_URL)
        try:
            await conn.execute("SELECT 1")
            return {"status": "ok"}
        finally:
            await conn.close()
    except Exception:
        return {"status": "error"}

async def _check_providers() -> dict[str, dict[str, str]]:
    results: dict[str, dict[str, str]] = {}
    for provider in ["anthropic", "openai", "ollama"]:
        try:
            results[provider] = {"status": "ok" if await health_check(provider) else "error"}
        except Exception:
            results[provider] = {"status": "error"}
    return results

async def health_check(provider_name: str) -> bool:
    check_func = _PROVIDER_CHECKS.get(provider_name)
    if check_func is None:
        raise ValueError(f"No health check function defined for provider '{provider_name}'")
    return await check_func()

def _overall_status(
    redis: dict[str, str],
    database: dict[str, str],
    providers: dict[str, dict[str, str]],
) -> str:
    if redis["status"] == "error":
        return "error"
    if database["status"] == "error":
        return "error"
    if any(p["status"] == "error" for p in providers.values()):
        return "degraded"
    return "ok"


@router.get("/health")
async def health(response: Response) -> dict:
    redis = await _check_redis()
    database = await _check_database()
    providers = await _check_providers()
    service_status = _overall_status(redis, database, providers)

    if service_status == "error":
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return {
        "status": service_status,
        "redis": redis,
        "database": database,
        "providers": providers,
    }


@router.get("/metrics")
async def metrics() -> PlainTextResponse:
    return PlainTextResponse(
        _METRICS_STUB,
        media_type="text/plain; version=0.0.4; charset=utf-8",
    )

