# app/providers/ollama_provider.py

import httpx
from app.schemas.provider import ProviderConfig
from app.config.settings import settings

OLLAMA_CONFIG = ProviderConfig(
    name               = "ollama",
    default_model      = "qwen3.5:4b",
    api_key_env_var    = "",
    priority           = 1,
    max_context_tokens = 256_000,
)

# Reads from settings, which reads from .env / docker-compose environment block.
# Never hardcode localhost here — from inside Docker, localhost means this
# container, not the Ollama container.
OLLAMA_BASE_URL = settings.OLLAMA_BASE_URL or "http://ollama:11434"


async def health_check() -> bool:
    try:
        async with httpx.AsyncClient(timeout=3) as client:
            r = await client.get(f"{OLLAMA_BASE_URL}/api/tags")
        if r.status_code != 200:
            return False
        models = r.json().get("models", [])
        return any(m["name"].startswith("qwen3.5") for m in models)
    except Exception:
        return False